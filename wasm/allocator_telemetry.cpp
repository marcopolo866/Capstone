#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include <emscripten/emscripten.h>

extern "C" {
void *__real_malloc(size_t size);
void *__real_calloc(size_t count, size_t size);
void *__real_realloc(void *ptr, size_t size);
void __real_free(void *ptr);
}

namespace {

constexpr size_t kAllocTableSize = 1u << 17; // 131072 slots
constexpr uintptr_t kPtrEmpty = 0u;
constexpr uintptr_t kPtrTombstone = 1u;

struct AllocationEntry {
    uintptr_t ptr;
    size_t size;
};

static AllocationEntry g_alloc_table[kAllocTableSize];

static uint64_t g_current_bytes = 0;
static uint64_t g_alloc_count_total = 0;
static uint64_t g_free_count_total = 0;
static uint64_t g_dropped_records_total = 0;

static uint64_t g_run_baseline_current = 0;
static uint64_t g_run_peak_current = 0;
static uint64_t g_run_alloc_count_base = 0;
static uint64_t g_run_free_count_base = 0;
static uint64_t g_run_dropped_records_base = 0;

inline size_t hash_ptr(uintptr_t ptr) {
    // Simple integer mix; pointers are 32-bit in wasm32.
    uintptr_t x = ptr;
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    x *= 0x846ca68bu;
    x ^= x >> 16;
    return static_cast<size_t>(x) & (kAllocTableSize - 1u);
}

inline uint64_t sat_add_u64(uint64_t a, uint64_t b) {
    const uint64_t out = a + b;
    if (out < a) return UINT64_MAX;
    return out;
}

inline uint64_t sat_sub_u64(uint64_t a, uint64_t b) {
    return (a >= b) ? (a - b) : 0;
}

size_t find_slot_for_insert_or_update(uintptr_t ptr, bool *found) {
    size_t idx = hash_ptr(ptr);
    size_t first_tombstone = kAllocTableSize;

    for (size_t i = 0; i < kAllocTableSize; ++i) {
        AllocationEntry &entry = g_alloc_table[idx];
        if (entry.ptr == ptr) {
            if (found) *found = true;
            return idx;
        }
        if (entry.ptr == kPtrEmpty) {
            if (found) *found = false;
            return (first_tombstone < kAllocTableSize) ? first_tombstone : idx;
        }
        if (entry.ptr == kPtrTombstone && first_tombstone == kAllocTableSize) {
            first_tombstone = idx;
        }
        idx = (idx + 1u) & (kAllocTableSize - 1u);
    }

    if (found) *found = false;
    return first_tombstone;
}

bool find_size(uintptr_t ptr, size_t *size_out) {
    size_t idx = hash_ptr(ptr);
    for (size_t i = 0; i < kAllocTableSize; ++i) {
        const AllocationEntry &entry = g_alloc_table[idx];
        if (entry.ptr == ptr) {
            if (size_out) *size_out = entry.size;
            return true;
        }
        if (entry.ptr == kPtrEmpty) return false;
        idx = (idx + 1u) & (kAllocTableSize - 1u);
    }
    return false;
}

bool upsert_allocation(uintptr_t ptr, size_t size) {
    if (ptr <= kPtrTombstone) return false;
    bool found = false;
    const size_t idx = find_slot_for_insert_or_update(ptr, &found);
    if (idx >= kAllocTableSize) {
        g_dropped_records_total = sat_add_u64(g_dropped_records_total, 1);
        return false;
    }
    g_alloc_table[idx].ptr = ptr;
    g_alloc_table[idx].size = size;
    return true;
}

size_t remove_allocation(uintptr_t ptr, bool *removed) {
    if (removed) *removed = false;
    if (ptr <= kPtrTombstone) return 0;

    size_t idx = hash_ptr(ptr);
    for (size_t i = 0; i < kAllocTableSize; ++i) {
        AllocationEntry &entry = g_alloc_table[idx];
        if (entry.ptr == ptr) {
            const size_t old_size = entry.size;
            entry.ptr = kPtrTombstone;
            entry.size = 0;
            if (removed) *removed = true;
            return old_size;
        }
        if (entry.ptr == kPtrEmpty) return 0;
        idx = (idx + 1u) & (kAllocTableSize - 1u);
    }

    return 0;
}

void on_alloc_success(size_t bytes) {
    g_alloc_count_total = sat_add_u64(g_alloc_count_total, 1);
    g_current_bytes = sat_add_u64(g_current_bytes, static_cast<uint64_t>(bytes));
    if (g_current_bytes > g_run_peak_current) g_run_peak_current = g_current_bytes;
}

void on_free_event(size_t bytes) {
    g_free_count_total = sat_add_u64(g_free_count_total, 1);
    g_current_bytes = sat_sub_u64(g_current_bytes, static_cast<uint64_t>(bytes));
}

inline uint64_t run_peak_delta_bytes() {
    return sat_sub_u64(g_run_peak_current, g_run_baseline_current);
}

inline uint64_t run_current_delta_bytes() {
    return sat_sub_u64(g_current_bytes, g_run_baseline_current);
}

} // namespace

extern "C" {

EMSCRIPTEN_KEEPALIVE
void capstone_allocator_telemetry_reset() {
    g_run_baseline_current = g_current_bytes;
    g_run_peak_current = g_current_bytes;
    g_run_alloc_count_base = g_alloc_count_total;
    g_run_free_count_base = g_free_count_total;
    g_run_dropped_records_base = g_dropped_records_total;
}

EMSCRIPTEN_KEEPALIVE
double capstone_allocator_telemetry_peak_bytes() {
    return static_cast<double>(run_peak_delta_bytes());
}

EMSCRIPTEN_KEEPALIVE
double capstone_allocator_telemetry_current_bytes() {
    return static_cast<double>(run_current_delta_bytes());
}

EMSCRIPTEN_KEEPALIVE
double capstone_allocator_telemetry_alloc_count() {
    return static_cast<double>(sat_sub_u64(g_alloc_count_total, g_run_alloc_count_base));
}

EMSCRIPTEN_KEEPALIVE
double capstone_allocator_telemetry_free_count() {
    return static_cast<double>(sat_sub_u64(g_free_count_total, g_run_free_count_base));
}

EMSCRIPTEN_KEEPALIVE
double capstone_allocator_telemetry_dropped_records() {
    return static_cast<double>(sat_sub_u64(g_dropped_records_total, g_run_dropped_records_base));
}

void *__wrap_malloc(size_t size) {
    void *ptr = __real_malloc(size);
    if (!ptr) return ptr;

    if (upsert_allocation(reinterpret_cast<uintptr_t>(ptr), size)) {
        on_alloc_success(size);
    } else {
        g_alloc_count_total = sat_add_u64(g_alloc_count_total, 1);
    }
    return ptr;
}

void *__wrap_calloc(size_t count, size_t size) {
    void *ptr = __real_calloc(count, size);
    if (!ptr) return ptr;

    size_t bytes = 0;
    if (count != 0 && size != 0) {
        if (SIZE_MAX / count < size) {
            bytes = SIZE_MAX;
        } else {
            bytes = count * size;
        }
    }

    if (upsert_allocation(reinterpret_cast<uintptr_t>(ptr), bytes)) {
        on_alloc_success(bytes);
    } else {
        g_alloc_count_total = sat_add_u64(g_alloc_count_total, 1);
    }
    return ptr;
}

void *__wrap_realloc(void *ptr, size_t size) {
    const uintptr_t old_ptr = reinterpret_cast<uintptr_t>(ptr);
    size_t old_size = 0;
    const bool had_old = (ptr != nullptr) && find_size(old_ptr, &old_size);

    void *out = __real_realloc(ptr, size);

    if (!out && size != 0) {
        // Allocation failed; old block remains valid.
        return nullptr;
    }

    if (ptr != nullptr) {
        bool removed = false;
        size_t removed_size = 0;
        if (had_old) removed_size = remove_allocation(old_ptr, &removed);
        on_free_event(removed ? removed_size : 0);
    }

    if (out != nullptr) {
        if (upsert_allocation(reinterpret_cast<uintptr_t>(out), size)) {
            on_alloc_success(size);
        } else {
            g_alloc_count_total = sat_add_u64(g_alloc_count_total, 1);
        }
    }

    return out;
}

void __wrap_free(void *ptr) {
    if (ptr != nullptr) {
        bool removed = false;
        const size_t removed_size = remove_allocation(reinterpret_cast<uintptr_t>(ptr), &removed);
        on_free_event(removed ? removed_size : 0);
    }
    __real_free(ptr);
}

} // extern "C"
