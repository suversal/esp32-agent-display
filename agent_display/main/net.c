#include "net.h"
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board_pins.h"
#include "secrets.h"
#include "cJSON.h"
#include "esp_event.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "lwip/inet.h"
#include "mdns.h"
#include "model.h"
#include "audio.h"
#include "nvs.h"
#include "nvs_flash.h"

#define MAX_MESSAGE 65536
static const char *TAG = "agent_net";
static bool configured, first_snapshot = true, assembling;
static atomic_bool wifi_up, socket_up, socket_ended, hello_pending, snapshot_ready;
static atomic_bool auto_page = true;
typedef enum { CONTROL_ACK, CONTROL_NEXT, CONTROL_AUTO } control_kind_t;
typedef struct { control_kind_t kind; char alert_id[65]; } control_t;
static QueueHandle_t control_queue;
static char *rx;
static size_t rx_len, frame_base;
static uint64_t last_sound_seq;
static char last_test_id[65];
static void publish_network(void)
{
    bool wifi = atomic_load(&wifi_up);
    model_network(configured, wifi, wifi && atomic_load(&socket_up) &&
                  atomic_load(&snapshot_ready));
}
static bool load_wifi(wifi_config_t *config)
{
    memset(config, 0, sizeof(*config));
    if (WIFI_SSID[0]) {
        if (strlen(WIFI_SSID) > sizeof(config->sta.ssid) ||
            strlen(WIFI_PASSWORD) > sizeof(config->sta.password)) return false;
        memcpy(config->sta.ssid, WIFI_SSID, strlen(WIFI_SSID));
        memcpy(config->sta.password, WIFI_PASSWORD, strlen(WIFI_PASSWORD));
        return true;
    }
    nvs_handle_t nvs;
    if (nvs_open("wifi", NVS_READONLY, &nvs) != ESP_OK) return false;
    bool found = false;
    for (int i = 0; i < 10; i++) {
        char key[16], ssid[33], password[65] = {0};
        snprintf(key, sizeof(key), i ? "ssid%d" : "ssid", i);
        size_t size = sizeof(ssid);
        if (nvs_get_str(nvs, key, ssid, &size) != ESP_OK || !ssid[0]) continue;
        snprintf(key, sizeof(key), i ? "password%d" : "password", i);
        size = sizeof(password);
        esp_err_t err = nvs_get_str(nvs, key, password, &size);
        if (err != ESP_OK && err != ESP_ERR_NVS_NOT_FOUND) continue;
        memcpy(config->sta.ssid, ssid, strlen(ssid));
        memcpy(config->sta.password, password, strlen(password));
        found = true;
        break;
    }
    nvs_close(nvs);
    return found;
}
static void wifi_event(void *arg, esp_event_base_t base, int32_t event, void *data)
{
    (void)arg; (void)data;
    if (base == IP_EVENT && event == IP_EVENT_STA_GOT_IP) {
        atomic_store(&wifi_up, true);
        ESP_LOGI(TAG, "WIFI_CONNECTED");
    } else if (base == WIFI_EVENT && event == WIFI_EVENT_STA_DISCONNECTED) {
        audio_cancel();
        atomic_store(&wifi_up, false);
        atomic_store(&snapshot_ready, false);
        ESP_LOGW(TAG, "WIFI_DISCONNECTED");
    }
    publish_network();
}
static void receive_data(const esp_websocket_event_data_t *e)
{
    // Control frames may appear between data fragments; they do not reset assembly.
    if (e->op_code != 0x1 && e->op_code != 0x0) return;
    if (e->payload_offset == 0) {
        if (e->op_code == 0x1) { rx_len = 0; assembling = true; }
        if (!assembling) return;
        frame_base = rx_len;
    }
    if (!assembling || e->data_len < 0 || e->payload_offset < 0 || e->payload_len < 0 ||
        (size_t)e->payload_len > MAX_MESSAGE - frame_base ||
        e->payload_offset > e->payload_len ||
        e->data_len > e->payload_len - e->payload_offset ||
        frame_base + (size_t)e->payload_offset != rx_len) {
        assembling = false;
        ESP_LOGW(TAG, "SNAPSHOT_FRAME_REJECTED");
        return;
    }
    if (e->data_len) memcpy(rx + rx_len, e->data_ptr, e->data_len);
    rx_len += e->data_len;
    if (e->fin && e->payload_offset + e->data_len == e->payload_len) {
        rx[rx_len] = 0;
        assembling = false;
        static display_snapshot_t snapshot;
        if (!protocol_parse(rx, rx_len, &snapshot)) {
            tone_kind_t kind;
            char id[65];
            if (protocol_parse_sound_test(rx, rx_len, &kind, id)) {
                if (strcmp(id, last_test_id)) {
                    snprintf(last_test_id, sizeof(last_test_id), "%s", id);
                    bool queued = audio_request(kind, 0, true);
                    ESP_LOGI(TAG, "SOUND_TEST kind=%s queued=%u", tone_name(kind), queued);
                }
                return;
            }
            ESP_LOGW(TAG, "SNAPSHOT_JSON_REJECTED bytes=%u", (unsigned)rx_len);
            return;
        }
        bool first = first_snapshot;
        bool sound = protocol_consume_sound(&snapshot, &first_snapshot, &last_sound_seq);
        audio_sync_alert(snapshot.has_alert ? snapshot.alert_id : "");
        if (snapshot.paged) atomic_store(&auto_page, snapshot.page_auto);
        model_snapshot(&snapshot);
        atomic_store(&snapshot_ready, true);
        publish_network();
        unsigned waiting = 0, running = 0, done = 0, stale = 0;
        for (size_t i = 0; i < snapshot.card_count; i++) {
            waiting += !strcmp(snapshot.cards[i].state, "waiting");
            running += !strcmp(snapshot.cards[i].state, "running");
            done += !strcmp(snapshot.cards[i].state, "done");
            stale += snapshot.cards[i].stale;
        }
        ESP_LOGI(TAG, "SNAPSHOT_READY sessions=%u waiting=%u running=%u done=%u stale=%u first=%u seq=%" PRIu64,
            (unsigned)snapshot.total_sessions, waiting, running, done, stale, first,
            snapshot.current_sound_seq);
        if (sound) {
            bool queued = audio_request(tone_kind(snapshot.alert_sound), snapshot.alert_sound_seq, false);
            ESP_LOGI(TAG, "SOUND_REQUEST kind=%s seq=%" PRIu64 " queued=%u",
                     snapshot.alert_sound, snapshot.alert_sound_seq, queued);
        }
    }
}
static void ws_event(void *arg, esp_event_base_t base, int32_t event, void *data)
{
    (void)arg; (void)base;
    if (event == WEBSOCKET_EVENT_CONNECTED) {
        first_snapshot = true;
        last_test_id[0] = 0;
        assembling = false;
        rx_len = 0;
        atomic_store(&snapshot_ready, false);
        atomic_store(&socket_up, true);
        atomic_store(&hello_pending, true);
        audio_cancel();
        ESP_LOGI(TAG, "BRIDGE_CONNECTED");
        publish_network();
    } else if (event == WEBSOCKET_EVENT_DISCONNECTED || event == WEBSOCKET_EVENT_CLOSED ||
               event == WEBSOCKET_EVENT_ERROR) {
        atomic_store(&socket_up, false);
        atomic_store(&snapshot_ready, false);
        atomic_store(&socket_ended, true);
        audio_cancel();
        ESP_LOGW(TAG, "BRIDGE_DISCONNECTED event=%" PRIi32, event);
        publish_network();
    } else if (event == WEBSOCKET_EVENT_DATA) receive_data(data);
}
static bool resolve_host(char *ip, size_t size)
{
    esp_ip4_addr_t address;
    if (BRIDGE_HOST[0] && mdns_query_a(BRIDGE_HOST, 1500, &address) == ESP_OK) {
        snprintf(ip, size, IPSTR, IP2STR(&address));
        ESP_LOGI(TAG, "BRIDGE_ADDRESS_RESOLVED source=mdns");
        return true;
    }
    if (BRIDGE_FALLBACK_IP[0] && inet_pton(AF_INET, BRIDGE_FALLBACK_IP, &address) == 1) {
        snprintf(ip, size, "%s", BRIDGE_FALLBACK_IP);
        ESP_LOGI(TAG, "BRIDGE_ADDRESS_RESOLVED source=fallback");
        return true;
    }
    return false;
}
static int64_t next_attempt(unsigned *delay)
{
    unsigned seconds = *delay;
    *delay = seconds < 16 ? seconds * 2 : 30;
    return esp_timer_get_time() + seconds * 1000000LL;
}
static void network_task(void *arg)
{
    (void)arg;
    unsigned wifi_delay = 1, ws_delay = 1;
    int64_t wifi_next = 0, ws_next = 0, connecting_since = 0;
    esp_websocket_client_handle_t client = NULL;
    bool hello_sent = false;
    while (true) {
        int64_t now = esp_timer_get_time();
        bool wifi = atomic_load(&wifi_up);
        if (client && (!wifi || atomic_load(&socket_ended) ||
                       (!atomic_load(&socket_up) && now - connecting_since > 15000000))) {
            // The WebSocket callback must never stop/destroy its own worker.
            esp_websocket_client_stop(client);
            esp_websocket_client_destroy(client);
            client = NULL;
            atomic_store(&socket_up, false);
            atomic_store(&snapshot_ready, false);
            atomic_store(&hello_pending, false);
            xQueueReset(control_queue);
            hello_sent = false;
            publish_network();
            ws_next = next_attempt(&ws_delay);
        }
        if (!wifi && now >= wifi_next) {
            esp_err_t err = esp_wifi_connect();
            ESP_LOGI(TAG, "WIFI_CONNECT_ATTEMPT code=%d", (int)err);
            wifi_next = next_attempt(&wifi_delay);
        }
        if (wifi) {
            wifi_delay = 1;
            wifi_next = 0;
        }
        if (wifi && !client && now >= ws_next) {
            char ip[16], uri[512];
            if (resolve_host(ip, sizeof(ip))) {
                int len = snprintf(uri, sizeof(uri), "ws://%s:%d/ws?token=%s",
                                   ip, BRIDGE_PORT, BRIDGE_TOKEN_URLENCODED);
                if (len > 0 && len < sizeof(uri)) {
                    esp_websocket_client_config_t config = {
                        .uri = uri, .disable_auto_reconnect = true, .task_stack = 8192,
                        .buffer_size = 4096, .network_timeout_ms = 5000,
                        .ping_interval_sec = 15, .pingpong_timeout_sec = 5,
                    };
                    atomic_store(&socket_ended, false);
                    client = esp_websocket_client_init(&config);
                    if (client) {
                        esp_websocket_register_events(client, WEBSOCKET_EVENT_ANY, ws_event, NULL);
                        connecting_since = esp_timer_get_time();
                        if (esp_websocket_client_start(client) != ESP_OK) atomic_store(&socket_ended, true);
                    }
                }
            }
            if (!client) ws_next = next_attempt(&ws_delay);
        }
        if (client && atomic_load(&socket_up)) {
            ws_delay = 1;
            if (atomic_exchange(&hello_pending, false)) {
                char hello[128];
                snprintf(hello, sizeof(hello), "{\"type\":\"hello\",\"fw\":\"%s\",\"paging\":true,\"auto_page\":%s}",
                         FW_VERSION, atomic_load(&auto_page) ? "true" : "false");
                hello_sent = esp_websocket_client_send_text(client, hello, strlen(hello), pdMS_TO_TICKS(1000)) == strlen(hello);
                ESP_LOGI(TAG, "HELLO_SENT ok=%u", hello_sent);
            }
            control_t control;
            if (hello_sent && xQueueReceive(control_queue, &control, 0) == pdTRUE) {
                cJSON *ack = cJSON_CreateObject();
                if (control.kind == CONTROL_ACK) {
                    cJSON_AddStringToObject(ack, "type", "ack");
                    cJSON_AddStringToObject(ack, "alert_id", control.alert_id);
                } else {
                    cJSON_AddStringToObject(ack, "type", "page");
                    cJSON_AddStringToObject(ack, "action", control.kind == CONTROL_AUTO ? "toggle_auto" : "next");
                }
                char *json = cJSON_PrintUnformatted(ack);
                if (json) {
                    bool ok = esp_websocket_client_send_text(client, json, strlen(json), pdMS_TO_TICKS(1000)) == strlen(json);
                    if (control.kind == CONTROL_ACK) ESP_LOGI(TAG, "ACK_SENT ok=%u", ok);
                    else ESP_LOGI(TAG, "PAGE_SENT toggle=%u ok=%u", control.kind == CONTROL_AUTO, ok);
                    cJSON_free(json);
                }
                cJSON_Delete(ack);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(200));
    }
}
esp_err_t net_start(void)
{
    // Transport errors can include the complete token-bearing URI.
    const char *private_tags[] = {"websocket_client", "transport_ws", "TRANSPORT_WS",
                                 "transport_base", "esp-tls", "wifi", "esp_netif_handlers"};
    for (size_t i = 0; i < sizeof(private_tags) / sizeof(private_tags[0]); i++)
        esp_log_level_set(private_tags[i], ESP_LOG_NONE);
    esp_err_t err = nvs_flash_init();
    if (err != ESP_OK) return err; // Never erase the user's existing configuration.
    wifi_config_t wifi;
    configured = load_wifi(&wifi);
    publish_network();
    if (!configured) {
        ESP_LOGW(TAG, "WIFI_CONFIG_UNAVAILABLE");
        return ESP_OK;
    }
    if (!BRIDGE_TOKEN_URLENCODED[0]) return ESP_ERR_INVALID_ARG;
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif init");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "event loop");
    if (!esp_netif_create_default_wifi_sta()) return ESP_ERR_NO_MEM;
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&init), TAG, "wifi init");
    ESP_RETURN_ON_ERROR(esp_wifi_set_storage(WIFI_STORAGE_RAM), TAG, "wifi RAM config");
    ESP_RETURN_ON_ERROR(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event, NULL), TAG, "wifi event");
    ESP_RETURN_ON_ERROR(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event, NULL), TAG, "IP event");
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "wifi mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &wifi), TAG, "wifi config");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "wifi start");
    ESP_RETURN_ON_ERROR(mdns_init(), TAG, "mdns init");
    rx = heap_caps_malloc(MAX_MESSAGE + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!rx) return ESP_ERR_NO_MEM;
    control_queue = xQueueCreate(4, sizeof(control_t));
    if (!control_queue) return ESP_ERR_NO_MEM;
    return xTaskCreate(network_task, "agent_network", 8192, NULL, 4, NULL) == pdPASS ?
           ESP_OK : ESP_ERR_NO_MEM;
}
void net_ack(const char *alert_id)
{
    if (!control_queue || !alert_id || !atomic_load(&socket_up)) return;
    audio_cancel();
    control_t control = {.kind = CONTROL_ACK};
    snprintf(control.alert_id, sizeof(control.alert_id), "%s", alert_id);
    if (xQueueSend(control_queue, &control, 0) != pdTRUE) ESP_LOGW(TAG, "ACK_QUEUE_FULL");
}
void net_page(bool toggle_auto)
{
    if (!control_queue || !atomic_load(&socket_up)) return;
    control_t control = {.kind = toggle_auto ? CONTROL_AUTO : CONTROL_NEXT};
    if (xQueueSend(control_queue, &control, 0) != pdTRUE) ESP_LOGW(TAG, "PAGE_QUEUE_FULL");
}
