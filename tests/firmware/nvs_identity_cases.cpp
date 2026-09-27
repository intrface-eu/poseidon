// Actual nvs_boot_identity.cpp links to these explicitly synthetic host ABI fakes.
#include "poseidon/nvs_boot_identity.hpp"
#include "nvs_flash.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <thread>
#include <type_traits>
#include <vector>

using poseidon::reef::JournalError;
using poseidon::reef::NvsBootIdentity;
using poseidon::reef::PartitionSpec;
static_assert(!std::is_copy_constructible<NvsBootIdentity>::value, "identity must not be copied");
static_assert(!std::is_move_constructible<NvsBootIdentity>::value, "identity owner must not move");
static_assert(std::is_base_of<poseidon::reef::BootIdentity, poseidon::reef::BootJournal>::value, "old journal remains an identity allocator");

namespace fake {
void check(bool value, const char* reason) { if (!value) throw std::runtime_error(reason); }
using Bytes = std::vector<std::uint8_t>;
Bytes from_hex(const std::string& text) {
    Bytes bytes;
    for (std::size_t i = 0; i < text.size(); i += 2) bytes.push_back(static_cast<std::uint8_t>(std::stoul(text.substr(i, 2), nullptr, 16)));
    return bytes;
}
void seal_crc(Bytes& bytes) {
    std::uint32_t checksum = 0xffffffff;
    for (std::size_t i = 0; i < 24; ++i) {
        checksum ^= bytes[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            checksum = checksum & 1 ? (checksum >> 1) ^ 0xedb88320U : checksum >> 1;
    }
    checksum ^= 0xffffffff;
    for (unsigned i = 0; i < 4; ++i) bytes[24 + i] = static_cast<std::uint8_t>(checksum >> (i * 8));
}
Bytes record(std::uint64_t floor) {
    Bytes bytes(32);
    bytes[0] = 'R'; bytes[1] = 'N'; bytes[2] = 'V'; bytes[3] = 'S'; bytes[4] = bytes[5] = 1;
    for (unsigned i = 0; i < 8; ++i) {
        bytes[8 + i] = static_cast<std::uint8_t>(floor >> (i * 8));
        bytes[16 + i] = static_cast<std::uint8_t>(~floor >> (i * 8));
    }
    seal_crc(bytes);
    return bytes;
}
thread_local TaskHandle_t task = reinterpret_cast<void*>(1);
struct World {
    esp_partition_t partition{nullptr, ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_DATA_NVS,
        0x3f0000, 0x10000, 0x1000, "reef_state", false, false};
    bool partition_present = true;
    std::size_t non_erased_offset = 0;
    bool initialized = false, namespace_exists = true, key_exists = true, blob_type = true;
    bool handle_open = false;
    nvs_open_mode_t mode = NVS_READONLY;
    Bytes persisted = record(0), pending;
    std::vector<std::string> calls;
    unsigned task_calls = 0, partition_reads = 0, get_calls = 0, close_calls = 0, deinit_calls = 0, ro_opens = 0, rw_opens = 0, sets = 0, commits = 0;
    esp_err_t stats_error = ESP_OK, init_error = ESP_OK, deinit_error = ESP_OK;
    esp_err_t ro_error = ESP_OK, rw_error = ESP_OK, set_error = ESP_OK, commit_error = ESP_OK;
    esp_err_t read_error = ESP_ERR_TIMEOUT, get_error = ESP_ERR_TIMEOUT;
    unsigned partition_read_failure = 0, get_failure = 0;
    bool init_changes_before_error = false, early_set = false, commit_changes_before_error = false;
    bool commit_no_effect = false, corrupt_after_commit = false, shorten_get_result = false;
    bool change_on_rw = false;
    std::function<void(const char*)> callback;
    bool in_callback = false;
    void call(const char* name) {
        calls.emplace_back(name);
        if (callback && !in_callback) { in_callback = true; callback(name); in_callback = false; }
    }
} world;
void label(const char* value) { check(value && std::strcmp(value, "reef_state") == 0, "no default/alternate partition fallback"); }
void key(const char* value) { check(value && std::strcmp(value, "identity_v1") == 0, "fixed record key"); }
void valid_handle(nvs_handle_t handle) { check(world.handle_open && handle == 91, "operate only on genuine owned handle"); }
std::size_t io_calls() { return world.calls.size() + world.task_calls; }
} // namespace fake

extern "C" TaskHandle_t xTaskGetCurrentTaskHandle() { ++fake::world.task_calls; return fake::task; }
extern "C" const esp_partition_t* esp_partition_find_first(esp_partition_type_t type, esp_partition_subtype_t subtype, const char* name) {
    fake::world.call("find"); fake::label(name);
    fake::check(type == ESP_PARTITION_TYPE_DATA && subtype == ESP_PARTITION_SUBTYPE_DATA_NVS, "fixed partition classification");
    return fake::world.partition_present ? &fake::world.partition : nullptr;
}
extern "C" esp_err_t esp_partition_read(const esp_partition_t* part, std::size_t offset, void* output, std::size_t length) {
    auto& w = fake::world; w.call("partition_read"); ++w.partition_reads;
    fake::check(part == &w.partition && length <= 256 && offset + length <= 0x10000, "bounded read-only erased preflight");
    if (w.partition_read_failure == w.partition_reads) return w.read_error;
    std::memset(output, 0xff, length);
    if (w.non_erased_offset >= offset && w.non_erased_offset < offset + length)
        static_cast<std::uint8_t*>(output)[w.non_erased_offset - offset] = 0;
    return ESP_OK;
}
extern "C" esp_err_t nvs_get_stats(const char* part, nvs_stats_t*) {
    auto& w = fake::world; w.call("stats"); fake::label(part);
    if (w.stats_error != ESP_OK) return w.stats_error;
    return w.initialized ? ESP_OK : ESP_ERR_NVS_NOT_INITIALIZED;
}
extern "C" esp_err_t nvs_flash_init_partition(const char* part) {
    auto& w = fake::world; w.call("init"); fake::label(part);
    if (w.init_error == ESP_OK || w.init_changes_before_error) w.initialized = true;
    return w.init_error;
}
extern "C" esp_err_t nvs_flash_deinit_partition(const char* part) {
    auto& w = fake::world; w.call("deinit"); fake::label(part); ++w.deinit_calls;
    fake::check(w.initialized && !w.handle_open, "deinit only initialized owned partition after closing handle");
    if (w.deinit_error == ESP_OK) w.initialized = false;
    return w.deinit_error;
}
extern "C" esp_err_t nvs_open_from_partition(const char* part, const char* space, nvs_open_mode_t mode, nvs_handle_t* output) {
    auto& w = fake::world; w.call(mode == NVS_READONLY ? "open_ro" : "open_rw"); fake::label(part);
    fake::check(w.initialized && !w.handle_open && std::strcmp(space, "reef_boot") == 0, "correct namespace and handle lifecycle");
    if (mode == NVS_READONLY) ++w.ro_opens; else ++w.rw_opens;
    const auto error = mode == NVS_READONLY ? w.ro_error : w.rw_error;
    if (error != ESP_OK) return error;
    if (!w.namespace_exists) return ESP_ERR_NVS_NOT_FOUND; // No implicit creation in this fake.
    if (mode == NVS_READWRITE && w.change_on_rw) w.persisted = fake::record(9);
    w.mode = mode; w.handle_open = true; *output = 91; return ESP_OK;
}
extern "C" esp_err_t nvs_get_blob(nvs_handle_t handle, const char* key, void* output, std::size_t* length) {
    auto& w = fake::world; w.call(output ? "get_body" : "get_length"); ++w.get_calls;
    fake::valid_handle(handle); fake::key(key);
    if (w.get_failure == w.get_calls) return w.get_error;
    if (!w.key_exists) return ESP_ERR_NVS_NOT_FOUND;
    if (!w.blob_type) return ESP_ERR_NVS_TYPE_MISMATCH;
    if (output && *length < w.persisted.size()) { *length = w.persisted.size(); return ESP_ERR_NVS_INVALID_LENGTH; }
    if (output) std::copy(w.persisted.begin(), w.persisted.end(), static_cast<std::uint8_t*>(output));
    *length = w.persisted.size();
    if (output && w.shorten_get_result && *length) --*length;
    return ESP_OK;
}
extern "C" esp_err_t nvs_set_blob(nvs_handle_t handle, const char* key, const void* value, std::size_t length) {
    auto& w = fake::world; w.call("set"); ++w.sets; fake::valid_handle(handle); fake::key(key);
    fake::check(w.mode == NVS_READWRITE && length == 32, "only complete existing identity record can be written");
    const auto* data = static_cast<const std::uint8_t*>(value);
    w.pending.assign(data, data + length);
    if (w.early_set) w.persisted = w.pending;
    return w.set_error;
}
extern "C" esp_err_t nvs_commit(nvs_handle_t handle) {
    auto& w = fake::world; w.call("commit"); ++w.commits; fake::valid_handle(handle);
    if ((w.commit_error == ESP_OK || w.commit_changes_before_error) && !w.commit_no_effect) w.persisted = w.pending;
    if (w.corrupt_after_commit) w.persisted[24] ^= 1;
    return w.commit_error;
}
extern "C" void nvs_close(nvs_handle_t handle) {
    auto& w = fake::world; w.call("close"); fake::valid_handle(handle); ++w.close_calls; w.handle_open = false;
}

namespace {
using fake::check;
void success_open(NvsBootIdentity& identity) { check(identity.open_existing() == JournalError::none, "open precommissioned synthetic record"); }
void check_process_latch(NvsBootIdentity& failed) {
    std::uint64_t output = 123;
    const auto before = fake::io_calls();
    check(failed.allocate_boot(output) != JournalError::none && output == 123, "faulted object does not publish or retry");
    check(fake::io_calls() == before, "fault retry makes no SDK calls");
    (void)failed.close();
    const auto closed = fake::io_calls();
    check(failed.open_existing() != JournalError::none, "same-object reopen cannot bypass process latch");
    NvsBootIdentity second(true);
    check(second.open_existing() != JournalError::none, "new object cannot bypass process latch");
    check(second.allocate_boot(output) != JournalError::none && output == 123, "new allocator cannot publish after uncertain write");
    check(fake::io_calls() == closed, "process latch blocks RTOS/partition/NVS access before opening");
}
void disabled() {
    { NvsBootIdentity identity; std::uint64_t out = 55; PartitionSpec bad; bad.label = nullptr;
      check(identity.open_existing() == JournalError::io, "disabled open rejects");
      check(identity.open_existing(bad) == JournalError::io, "disabled argument path rejects before examining backend");
      check(identity.allocate_boot(out) == JournalError::io && out == 55, "disabled allocation unchanged");
      check(identity.last_esp_error() == ESP_ERR_NOT_ALLOWED, "disabled diagnostic");
      check(identity.close() == JournalError::none, "disabled close no-op"); }
    check(fake::io_calls() == 0, "disabled constructor/open/allocate/close/destructor zero SDK and RTOS calls");
}
void success() {
    const auto baseline = fake::from_hex("524e5653010100000000000000000000ffffffffffffffff58fe44e800000000");
    check(fake::world.persisted == baseline, "independent Python zlib golden baseline");
    NvsBootIdentity first(true); check(fake::io_calls() == 0, "enabled construction is also zero I/O"); success_open(first);
    check(fake::world.ro_opens == 1 && fake::world.rw_opens == 1 && fake::world.get_calls == 4, "RO validate then RW revalidate");
    std::uint64_t output = 0; check(first.allocate_boot(output) == JournalError::none && output == 1, "baseline zero advances to one");
    check(fake::world.persisted == fake::from_hex("524e5653010100000100000000000000feffffffffffffff576f868a00000000"), "new record exact bytes and CRC");
    check(fake::world.sets == 1 && fake::world.commits == 1 && fake::world.get_calls == 8, "write commit readback before success");
    check(first.close() == JournalError::none && !fake::world.initialized && !fake::world.handle_open, "close owned handle and init");
    const auto closed = fake::io_calls(); check(first.close() == JournalError::none && fake::io_calls() == closed, "idempotent no-I/O close");
    NvsBootIdentity next(true); success_open(next);
    for (std::uint64_t n = 2; n <= 23; ++n) check(next.allocate_boot(output) == JournalError::none && output == n, "increasing floor across reopened object");
    check(fake::world.persisted == fake::from_hex("524e5653010100001700000000000000e8ffffffffffffff8100e48500000000"), "golden floor23");
}
void owner() {
    NvsBootIdentity first(true); success_open(first);
    NvsBootIdentity competitor(true); const auto calls = fake::world.calls.size();
    fake::task = reinterpret_cast<void*>(2);
    check(competitor.open_existing() == JournalError::io && fake::world.calls.size() == calls, "competing instance blocked before physical-interface calls");
    std::uint64_t output = 91;
    check(first.allocate_boot(output) == JournalError::io && output == 91 && fake::world.calls.size() == calls, "wrong worker cannot allocate");
    check(first.close() == JournalError::io && fake::world.handle_open, "wrong worker cannot close owned resources");
    fake::task = reinterpret_cast<void*>(1);
    check(first.allocate_boot(output) == JournalError::none && output == 1, "owner still valid after rejected outsider");
    check(first.close() == JournalError::none, "right owner cleanup");
    fake::task = reinterpret_cast<void*>(2); success_open(competitor);
    check(competitor.allocate_boot(output) == JournalError::none && output == 2, "lease transfers only after clean close");
}
void reentrant(bool threads) {
    NvsBootIdentity identity(true); success_open(identity);
    unsigned checks = 0;
    fake::world.callback = [&](const char* point) {
        if (std::strcmp(point, "set") != 0) return;
        const auto nested = [&] {
            if (threads) fake::task = reinterpret_cast<void*>(2);
            std::uint64_t output = 123;
            check(identity.allocate_boot(output) == JournalError::io && output == 123, "nested allocation rejected");
            check(identity.open_existing() == JournalError::io, "nested open rejected");
            check(identity.close() == JournalError::io, "nested cleanup rejected");
        };
        if (threads) { std::thread other(nested); other.join(); } else nested();
        ++checks;
    };
    std::uint64_t output = 0;
    check(identity.allocate_boot(output) == JournalError::none && output == 1 && checks == 1, "outer operation alone commits and publishes");
    check(fake::world.sets == 1 && fake::world.commits == 1, "no interleaved reentrant SDK calls");
    fake::world.callback = nullptr;
}
void open_failure(const std::string& kind) {
    auto& w = fake::world; PartitionSpec spec;
    JournalError expected = JournalError::io;
    esp_err_t error = ESP_ERR_INVALID_ARG;
    if (kind == "spec_label") spec.label = "nvs";
    else if (kind == "spec_null") spec.key = nullptr;
    else if (kind == "spec_address") spec.address = 0;
    else if (kind == "spec_size") spec.size = 0x20000;
    else if (kind == "spec_type") spec.type = ESP_PARTITION_TYPE_APP;
    else if (kind == "spec_subtype") spec.subtype = static_cast<esp_partition_subtype_t>(3);
    else if (kind == "spec_namespace") spec.namespace_name = "other";
    else if (kind == "spec_key") spec.key = "other";
    else if (kind == "task_null") { fake::task = nullptr; error = ESP_ERR_INVALID_STATE; }
    else if (kind == "partition_missing") { w.partition_present = false; error = ESP_ERR_NOT_FOUND; expected = JournalError::unprovisioned; }
    else if (kind == "partition_address") { w.partition.address = 0; expected = JournalError::corrupt; }
    else if (kind == "partition_size") { w.partition.size = 0x20000; expected = JournalError::corrupt; }
    else if (kind == "partition_label") { std::strcpy(w.partition.label, "nvs"); expected = JournalError::corrupt; }
    else if (kind == "partition_type") { w.partition.type = ESP_PARTITION_TYPE_APP; expected = JournalError::corrupt; }
    else if (kind == "partition_subtype") { w.partition.subtype = static_cast<esp_partition_subtype_t>(3); expected = JournalError::corrupt; }
    else if (kind == "partition_encrypted") { w.partition.encrypted = true; expected = JournalError::corrupt; }
    else if (kind == "partition_readonly") { w.partition.readonly = true; expected = JournalError::corrupt; }
    else if (kind == "erased") { w.non_erased_offset = SIZE_MAX; error = ESP_ERR_NVS_NOT_FOUND; expected = JournalError::unprovisioned; }
    else if (kind == "preflight_error") { w.partition_read_failure = 1; error = w.read_error; }
    else if (kind == "preflight_last_error") { w.non_erased_offset = SIZE_MAX; w.partition_read_failure = 256; error = w.read_error; }
    else if (kind == "externally_initialized") { w.initialized = true; error = ESP_ERR_INVALID_STATE; }
    else if (kind == "stats_error") { w.stats_error = ESP_ERR_TIMEOUT; error = w.stats_error; }
    else if (kind == "init_error" || kind == "init_partial") { w.init_error = ESP_ERR_NVS_NO_FREE_PAGES; w.init_changes_before_error = kind == "init_partial"; error = w.init_error; }
    else if (kind == "init_new_version") { w.init_error = ESP_ERR_NVS_NEW_VERSION_FOUND; error = w.init_error; expected = JournalError::corrupt; }
    else if (kind == "namespace_missing") { w.namespace_exists = false; error = ESP_ERR_NVS_NOT_FOUND; expected = JournalError::unprovisioned; }
    else if (kind == "ro_open_error") { w.ro_error = ESP_ERR_NO_MEM; error = w.ro_error; }
    else if (kind == "rw_open_error") { w.rw_error = ESP_ERR_NVS_NOT_ENOUGH_SPACE; error = w.rw_error; }
    else if (kind == "key_missing") { w.key_exists = false; error = ESP_ERR_NVS_NOT_FOUND; expected = JournalError::unprovisioned; }
    else if (kind == "wrong_type") { w.blob_type = false; error = ESP_ERR_NVS_TYPE_MISMATCH; expected = JournalError::corrupt; }
    else if (kind == "short_body") { w.shorten_get_result = true; error = ESP_ERR_NVS_INVALID_LENGTH; expected = JournalError::corrupt; }
    else if (kind == "changed_on_rw") { w.change_on_rw = true; error = ESP_ERR_INVALID_STATE; expected = JournalError::corrupt; }
    else if (kind.rfind("length_", 0) == 0) { w.persisted.resize(std::stoul(kind.substr(7))); error = ESP_ERR_NVS_INVALID_LENGTH; expected = JournalError::corrupt; }
    else if (kind.rfind("semantic_", 0) == 0) {
        const auto field = kind.substr(9);
        const auto byte = field == "magic" ? 0 : field == "version" ? 4 : field == "marker" ? 5 : field == "reserved" ? 6 : 16;
        w.persisted[byte] ^= 1; fake::seal_crc(w.persisted);
        error = ESP_ERR_INVALID_STATE; expected = JournalError::corrupt;
    }
    else if (kind.rfind("record_byte_", 0) == 0) { w.persisted.at(std::stoul(kind.substr(12))) ^= 1; error = ESP_ERR_INVALID_STATE; expected = JournalError::corrupt; }
    else if (kind.rfind("open_read_", 0) == 0) { w.get_failure = std::stoul(kind.substr(10)); error = w.get_error; }
    else throw std::runtime_error("unknown open failure");
    { NvsBootIdentity identity(true);
      check(identity.open_existing(spec) == expected, "open failure classified");
      check(identity.last_esp_error() == error, "exact native/policy error preserved");
      check(w.sets == 0 && w.commits == 0, "no namespace/baseline/record creation on bad startup");
      check(!w.handle_open, "open failure closes only successful handles");
      if (w.init_error != ESP_OK || kind == "externally_initialized") check(w.deinit_calls == 0, "never deinit initialization not owned");
      else check(!w.initialized, "successful initialization is cleaned on open failure");
      std::uint64_t output = 77; check(identity.allocate_boot(output) != JournalError::none && output == 77, "open failure cannot allocate"); }
    if (kind.rfind("spec_", 0) == 0) check(fake::io_calls() == 0, "invalid fixed spec has zero SDK calls");
    if (kind == "erased") check(w.partition_reads == 256 && w.ro_opens == 0 && w.deinit_calls == 0, "all-erased rejected before init");
    if (w.init_error != ESP_OK) {
        const auto calls = fake::io_calls(); NvsBootIdentity second(true);
        check(second.open_existing() == JournalError::io && fake::io_calls() == calls, "uncertain initialization cannot be retried by a new object");
    }
}
void allocation_failure(const std::string& kind) {
    auto& w = fake::world;
    if (kind == "max") w.persisted = fake::record(UINT64_MAX);
    NvsBootIdentity identity(true); success_open(identity);
    esp_err_t error = ESP_ERR_INVALID_STATE; JournalError expected = JournalError::io;
    if (kind == "set_error" || kind == "set_early_error") { w.set_error = ESP_ERR_NVS_REMOVE_FAILED; w.early_set = kind == "set_early_error"; error = w.set_error; }
    else if (kind == "commit_error" || kind == "commit_early_error") { w.commit_error = ESP_ERR_TIMEOUT; w.commit_changes_before_error = kind == "commit_early_error"; error = w.commit_error; }
    else if (kind == "readback_length" || kind == "readback_body") { w.get_failure = kind == "readback_length" ? 7 : 8; error = w.get_error; }
    else if (kind == "readback_corrupt") { w.corrupt_after_commit = true; expected = JournalError::corrupt; }
    else if (kind == "readback_old") { w.commit_no_effect = true; expected = JournalError::corrupt; }
    else if (kind == "prewrite_length" || kind == "prewrite_body") { w.get_failure = kind == "prewrite_length" ? 5 : 6; error = w.get_error; }
    else if (kind == "external_floor") { w.persisted = fake::record(9); expected = JournalError::corrupt; }
    else if (kind == "max") expected = JournalError::exhausted;
    else throw std::runtime_error("unknown allocation failure");
    std::uint64_t output = 999;
    check(identity.allocate_boot(output) == expected && output == 999, "failed allocation never publishes");
    check(identity.last_esp_error() == error, "exact failure retained");
    if (kind == "set_early_error" || kind == "commit_early_error") check(w.persisted == fake::record(1), "synthetic early write really changed backing state despite failure");
    const auto bytes = w.persisted;
    check_process_latch(identity);
    check(w.persisted == bytes, "error never restores/reseeds a presumed older floor");
}
void boundaries() {
    auto& w = fake::world;
    w.persisted = fake::from_hex("524e565301010000efcdab89674523011032547698badcfe67226d3400000000");
    { NvsBootIdentity identity(true); success_open(identity); std::uint64_t out = 0;
      check(identity.allocate_boot(out) == JournalError::none && out == 0x0123456789abcdf0ULL, "little-endian full-width floor"); }
    w.persisted = fake::record(UINT64_MAX - 1);
    NvsBootIdentity identity(true); success_open(identity); std::uint64_t output = 0;
    check(identity.allocate_boot(output) == JournalError::none && output == UINT64_MAX, "maximum ID published once");
    check(w.persisted == fake::from_hex("524e565301010000ffffffffffffffff000000000000000017734c3b00000000"), "uint64 maximum golden bytes");
    check(identity.allocate_boot(output) == JournalError::exhausted && output == UINT64_MAX, "no uint64 wrap");
    check_process_latch(identity);
}
void cleanup_failure(bool on_open) {
    auto& w = fake::world;
    NvsBootIdentity identity(true);
    if (on_open) { w.key_exists = false; w.deinit_error = ESP_ERR_TIMEOUT;
        check(identity.open_existing() == JournalError::io, "cleanup failure surfaced during failed open"); }
    else { success_open(identity); w.deinit_error = ESP_ERR_TIMEOUT;
        check(identity.close() == JournalError::io, "deinit failure surfaced"); }
    check(identity.last_esp_error() == ESP_ERR_TIMEOUT && w.deinit_calls == 1 && !w.handle_open, "deinit error preserves exact diagnostic, handle closes once");
    const auto calls = fake::io_calls();
    check(identity.close() == JournalError::io && fake::io_calls() == calls, "failed cleanup is quarantined, not retried");
    NvsBootIdentity next(true); check(next.open_existing() == JournalError::io && fake::io_calls() == calls, "cleanup uncertainty blocks process reuse");
}
void wrong_owner_destruction() {
    auto* identity = new NvsBootIdentity(true); success_open(*identity);
    fake::task = reinterpret_cast<void*>(2); delete identity;
    check(fake::world.handle_open && fake::world.deinit_calls == 0, "wrong-owner destructor must not close foreign-worker resources");
    const auto calls = fake::io_calls();
    NvsBootIdentity next(true); check(next.open_existing() == JournalError::io && fake::io_calls() == calls, "orphaned lifecycle poisons process without dangling lease");
}
void stats_partition_not_registered() {
    fake::world.stats_error = ESP_ERR_NVS_PART_NOT_FOUND;
    fake::world.non_erased_offset = 0xffff;
    NvsBootIdentity identity(true); success_open(identity);
    check(fake::world.partition_reads == 256, "last-byte non-erased preflight bounded");
    std::uint64_t output = 0; check(identity.allocate_boot(output) == JournalError::none && output == 1, "unregistered partition is initialized only after preflight");
}
void runtime_identity_compatibility() {
    class MissingSensor final : public poseidon::reef::Sensor {
        poseidon::reef::SensorReading sample() noexcept override { return {}; }
    } sensor;
    NvsBootIdentity identity(true); success_open(identity);
    poseidon::reef::Runtime runtime(identity, sensor);
    const poseidon::reef::ClockReading clock{};
    check(runtime.start(clock) == poseidon::reef::RuntimeResult::ready, "Runtime accepts NVS BootIdentity");
    check(runtime.poll(clock, {}) == poseidon::reef::RuntimeResult::sampled, "runtime samples missing provider honestly");
    check(runtime.front()->boot_id == 1 && !runtime.front()->sensor_value && !runtime.front()->battery_mv, "persisted ID with invalid/null providers");
}
} // namespace

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    const std::string name = argv[1];
    try {
        if (name == "disabled") disabled();
        else if (name == "success") success();
        else if (name == "owner") owner();
        else if (name == "reentrant") reentrant(false);
        else if (name == "concurrent") reentrant(true);
        else if (name == "boundaries") boundaries();
        else if (name == "cleanup_failure") cleanup_failure(false);
        else if (name == "open_cleanup_failure") cleanup_failure(true);
        else if (name == "wrong_owner_destruction") wrong_owner_destruction();
        else if (name == "stats_partition_not_registered") stats_partition_not_registered();
        else if (name == "runtime_compatibility") runtime_identity_compatibility();
        else if (name.rfind("open_", 0) == 0) open_failure(name.substr(5));
        else if (name.rfind("allocate_", 0) == 0) allocation_failure(name.substr(9));
        else throw std::runtime_error("unknown case");
        std::cout << "PASS " << name << '\n'; return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL " << name << ": " << error.what() << '\n'; return 1;
    }
}
