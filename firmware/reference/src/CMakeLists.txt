idf_component_register(
    SRCS "main.cpp" "ota_compile_reference.cpp" "../../reef/src/reef.cpp" "../../../libs/proto-cpp/src/telemetry.cpp"
    INCLUDE_DIRS "../../reef/include" "../../../libs/proto-cpp/include" "."
    REQUIRES app_update
)
target_compile_features(${COMPONENT_LIB} PUBLIC cxx_std_17)
