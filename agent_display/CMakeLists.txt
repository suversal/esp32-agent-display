cmake_minimum_required(VERSION 3.16)
set(WAVESHARE_COMPONENTS "${CMAKE_CURRENT_LIST_DIR}/../vendor/waveshare/02_Example/ESP-IDF/11_U8G2_Test/components")
set(EXTRA_COMPONENT_DIRS
    "${WAVESHARE_COMPONENTS}/u8g2"
    "${WAVESHARE_COMPONENTS}/u8g2_st7305")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(agent_display)
