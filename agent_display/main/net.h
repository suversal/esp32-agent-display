#pragma once
#include "esp_err.h"
#include <stdbool.h>
esp_err_t net_start(void);
void net_ack(const char *alert_id);
void net_page(bool toggle_auto);
