idf_component_register(
    SRCS "main.cpp" "../../reef/src/reef.cpp"
         "../../esp-idf/src/nvs_boot_identity.cpp" "../../esp-idf/src/monitor_task.cpp"
         "../../../libs/proto-cpp/src/telemetry.cpp"
    INCLUDE_DIRS "../../reef/include" "../../esp-idf/include" "../../../libs/proto-cpp/include"
    REQUIRES nvs_flash esp_timer esp_partition freertos
)
target_compile_features(${COMPONENT_LIB} PUBLIC cxx_std_17)
