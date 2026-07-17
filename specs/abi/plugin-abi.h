/*
 * Flow Plugin ABI — Version 1.0.0
 *
 * This header is the binding contract for Flow plugins. Plugins written in
 * any language that can produce a C-compatible shared library include this
 * header and export the required entry points.
 *
 * See: specs/plugin-abi.md for the full specification.
 */

#ifndef FLOW_PLUGIN_ABI_H
#define FLOW_PLUGIN_ABI_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- Versioning --------------------------------------------------------- */

#define FLOW_PLUGIN_ABI_VERSION_MAJOR 1
#define FLOW_PLUGIN_ABI_VERSION_MINOR 0
#define FLOW_PLUGIN_ABI_VERSION_PATCH 0

/* ---- Status codes ------------------------------------------------------- */

typedef enum FlowStatus {
    FLOW_OK                           = 0,
    FLOW_ERR_INVALID_ARGUMENT         = 1,
    FLOW_ERR_INVALID_STATE            = 2,
    FLOW_ERR_NOT_FOUND                = 3,
    FLOW_ERR_ALREADY_EXISTS           = 4,
    FLOW_ERR_OUT_OF_MEMORY            = 5,
    FLOW_ERR_IO                       = 6,
    FLOW_ERR_UNSUPPORTED              = 7,
    FLOW_ERR_VERSION_MISMATCH         = 8,
    FLOW_ERR_CANCELLED                = 9,
    FLOW_ERR_INTERNAL                 = 100
} FlowStatus;

/* ---- Forward declarations ---------------------------------------------- */

typedef struct FlowHost FlowHost;
typedef struct FlowBuffer FlowBuffer;
typedef struct FlowFrame FlowFrame;
typedef struct FlowEffectHandle FlowEffectHandle;

/* ---- Plugin info -------------------------------------------------------- */

typedef struct FlowPluginInfo {
    const char* id;                  /* reverse-DNS, e.g. "com.example.upscale" */
    const char* name;                /* human-readable */
    const char* version;             /* semver string */
    uint32_t     abi_version_major;
    uint32_t     abi_version_minor;
    uint32_t     abi_version_patch;
    const char* description;
    const char* author;
    const char* license;
} FlowPluginInfo;

/* ---- Effect declaration ------------------------------------------------- */

typedef struct FlowPortSpec {
    const char* name;
    const char* kind;                /* "video" | "audio" | "data" */
    const char* description;
} FlowPortSpec;

typedef struct FlowEffectDecl {
    const char* id;                  /* e.g. "com.example.upscale" */
    const char* name;                /* human-readable */
    const char* description;
    const char* param_schema_json;   /* JSON Schema for the params object */
    int         is_ai;
    size_t      num_inputs;
    const FlowPortSpec* inputs;
    size_t      num_outputs;
    const FlowPortSpec* outputs;
} FlowEffectDecl;

/* ---- Media linker declaration ------------------------------------------ */

typedef struct FlowLinkedMedia {
    const char* local_path;
    const char* content_type;        /* MIME type */
    int64_t     size_bytes;
    int64_t     duration_us;         /* microseconds, 0 if not applicable */
    int         width;
    int         height;
    double      fps;
} FlowLinkedMedia;

typedef struct FlowMediaLinkerDecl {
    const char* id;
    const char* name;
    const char* description;
} FlowMediaLinkerDecl;

/* ---- AI backend declaration -------------------------------------------- */

typedef enum FlowAiBackendKind {
    FLOW_AI_BACKEND_LOCAL_ONNX = 0,
    FLOW_AI_BACKEND_LOCAL_LIBTORCH = 1,
    FLOW_AI_BACKEND_REMOTE_HTTP = 2,
    FLOW_AI_BACKEND_WEBGPU = 3
} FlowAiBackendKind;

typedef struct FlowAiBackendDecl {
    const char* id;
    const char* name;
    FlowAiBackendKind kind;
    const char* config_schema_json;
} FlowAiBackendDecl;

/* ---- Host API (callable by plugins) ------------------------------------ */

typedef FlowStatus (*FlowHost_RegisterEffectFn)(
    FlowHost* host, const FlowEffectDecl* decl);
typedef FlowStatus (*FlowHost_RegisterMediaLinkerFn)(
    FlowHost* host, const FlowMediaLinkerDecl* decl);
typedef FlowStatus (*FlowHost_RegisterAiBackendFn)(
    FlowHost* host, const FlowAiBackendDecl* decl);
typedef int (*FlowHost_IsCancelledFn)(FlowHost* host);
typedef void (*FlowHost_LogFn)(
    FlowHost* host, int level, const char* message);
typedef FlowStatus (*FlowHost_BufferRefFn)(FlowBuffer* buffer);
typedef void (*FlowHost_BufferUnrefFn)(FlowBuffer* buffer);

typedef struct FlowHostVTable {
    FlowHost_RegisterEffectFn       register_effect;
    FlowHost_RegisterMediaLinkerFn  register_media_linker;
    FlowHost_RegisterAiBackendFn    register_ai_backend;
    FlowHost_IsCancelledFn          is_cancelled;
    FlowHost_LogFn                  log;
    FlowHost_BufferRefFn            buffer_ref;
    FlowHost_BufferUnrefFn          buffer_unref;
} FlowHostVTable;

struct FlowHost {
    const FlowHostVTable* vtable;
    void* userdata;
};

/* ---- Effect processing -------------------------------------------------- */

typedef struct FlowFrameBufferInfo {
    const uint8_t* data;
    size_t         size;
    int            width;
    int            height;
    int            format;            /* pixel format (matches AV_PIX_FMT_*) */
    int            sample_rate;
    int            channels;
    int64_t        nb_samples;
    int64_t        pts;               /* presentation timestamp, in stream timebase */
    int64_t        duration;          /* in stream timebase */
} FlowFrameBufferInfo;

struct FlowFrame {
    int   num_buffers;
    FlowFrameBufferInfo* buffers;
    void* userdata;
};

typedef void (*FlowProgressCallback)(void* userdata, double progress);

typedef FlowStatus (*FlowEffectProcessFn)(
    FlowEffectHandle effect,
    FlowFrame** inputs, size_t num_inputs,
    FlowFrame** outputs, size_t num_outputs,
    FlowProgressCallback progress_cb,
    void* progress_userdata);

typedef FlowStatus (*FlowEffectDestroyFn)(FlowEffectHandle effect);

typedef struct FlowEffectVTable {
    FlowEffectProcessFn process;
    FlowEffectDestroyFn destroy;
} FlowEffectVTable;

struct FlowEffectHandle {
    const FlowEffectVTable* vtable;
    void* userdata;
};

/* ---- Required plugin entry points -------------------------------------- */

/*
 * Returns information about the plugin. The runtime calls this first.
 * All returned strings must remain valid for the lifetime of the plugin
 * (typically static).
 */
FlowPluginInfo flow_plugin_info(void);

/*
 * Called after flow_plugin_info. The plugin registers its effects,
 * media linkers, and AI backends via the host's vtable.
 */
FlowStatus flow_plugin_register(FlowHost* host);

/*
 * Called by the runtime to instantiate an effect with the given params.
 * The plugin returns a FlowEffectHandle, or an error.
 *
 * params_json is a UTF-8 JSON string. The plugin must validate it against
 * the param_schema declared in the effect's FlowEffectDecl.
 */
typedef FlowStatus (*FlowEffectFactoryFn)(
    const char* effect_id,
    const char* params_json,
    FlowEffectHandle* out);

/*
 * The plugin must export a factory function named flow_create_effect.
 */
FlowStatus flow_create_effect(
    const char* effect_id,
    const char* params_json,
    FlowEffectHandle* out);

/*
 * The plugin must export a cleanup function for cleaning up global state
 * at unload time.
 */
void flow_plugin_shutdown(void);

#ifdef __cplusplus
}
#endif

#endif /* FLOW_PLUGIN_ABI_H */
