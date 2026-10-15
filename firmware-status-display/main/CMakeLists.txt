idf_component_register(SRCS "main.c" "model.c" "protocol.c" "ui.c" "net.c" "audio.c" "tone.c" "button.c"
    INCLUDE_DIRS "."
    REQUIRES u8g2_st7305 esp_timer esp_wifi esp_event esp_netif nvs_flash json
             esp_websocket_client mdns driver esp_codec_dev)
