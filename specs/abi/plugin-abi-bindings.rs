//! Flow Plugin ABI — Rust bindings
//!
//! This file is the **Rust view of the C ABI** defined in `plugin-abi.h`.
//! It is the binding contract for plugins written in Rust and for the
//! runtime's plugin loader.
//!
//! See: specs/plugin-abi.md for the full specification.

#![allow(non_camel_case_types)]

use std::os::raw::{c_char, c_int, c_void};

// ---- Versioning ----------------------------------------------------------

pub const FLOW_PLUGIN_ABI_VERSION_MAJOR: u32 = 1;
pub const FLOW_PLUGIN_ABI_VERSION_MINOR: u32 = 0;
pub const FLOW_PLUGIN_ABI_VERSION_PATCH: u32 = 0;

// ---- Status codes --------------------------------------------------------

#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum FlowStatus {
    Ok = 0,
    InvalidArgument = 1,
    InvalidState = 2,
    NotFound = 3,
    AlreadyExists = 4,
    OutOfMemory = 5,
    Io = 6,
    Unsupported = 7,
    VersionMismatch = 8,
    Cancelled = 9,
    Internal = 100,
}

// ---- Opaque handles ------------------------------------------------------

#[repr(C)]
pub struct FlowHost {
    pub vtable: *const FlowHostVTable,
    pub userdata: *mut c_void,
}

#[repr(C)]
pub struct FlowBuffer {
    _private: [u8; 0],
}

#[repr(C)]
pub struct FlowFrame {
    pub num_buffers: c_int,
    pub buffers: *mut FlowFrameBufferInfo,
    pub userdata: *mut c_void,
}

#[repr(C)]
pub struct FlowEffectHandle {
    pub vtable: *const FlowEffectVTable,
    pub userdata: *mut c_void,
}

// ---- Plugin info ---------------------------------------------------------

#[repr(C)]
pub struct FlowPluginInfo {
    pub id: *const c_char,
    pub name: *const c_char,
    pub version: *const c_char,
    pub abi_version_major: u32,
    pub abi_version_minor: u32,
    pub abi_version_patch: u32,
    pub description: *const c_char,
    pub author: *const c_char,
    pub license: *const c_char,
}

// ---- Port spec -----------------------------------------------------------

#[repr(C)]
pub struct FlowPortSpec {
    pub name: *const c_char,
    pub kind: *const c_char,
    pub description: *const c_char,
}

// ---- Effect declaration --------------------------------------------------

#[repr(C)]
pub struct FlowEffectDecl {
    pub id: *const c_char,
    pub name: *const c_char,
    pub description: *const c_char,
    pub param_schema_json: *const c_char,
    pub is_ai: c_int,
    pub num_inputs: usize,
    pub inputs: *const FlowPortSpec,
    pub num_outputs: usize,
    pub outputs: *const FlowPortSpec,
}

// ---- Media linker declaration --------------------------------------------

#[repr(C)]
pub struct FlowLinkedMedia {
    pub local_path: *const c_char,
    pub content_type: *const c_char,
    pub size_bytes: i64,
    pub duration_us: i64,
    pub width: c_int,
    pub height: c_int,
    pub fps: f64,
}

#[repr(C)]
pub struct FlowMediaLinkerDecl {
    pub id: *const c_char,
    pub name: *const c_char,
    pub description: *const c_char,
}

// ---- AI backend declaration ----------------------------------------------

#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
pub enum FlowAiBackendKind {
    LocalOnnx = 0,
    LocalLibtorch = 1,
    RemoteHttp = 2,
    WebGpu = 3,
}

#[repr(C)]
pub struct FlowAiBackendDecl {
    pub id: *const c_char,
    pub name: *const c_char,
    pub kind: FlowAiBackendKind,
    pub config_schema_json: *const c_char,
}

// ---- Frame buffer info ---------------------------------------------------

#[repr(C)]
pub struct FlowFrameBufferInfo {
    pub data: *const u8,
    pub size: usize,
    pub width: c_int,
    pub height: c_int,
    pub format: c_int,
    pub sample_rate: c_int,
    pub channels: c_int,
    pub nb_samples: i64,
    pub pts: i64,
    pub duration: i64,
}

// ---- Host vtable ---------------------------------------------------------

#[repr(C)]
pub struct FlowHostVTable {
    pub register_effect:
        unsafe extern "C" fn(host: *mut FlowHost, decl: *const FlowEffectDecl) -> FlowStatus,
    pub register_media_linker:
        unsafe extern "C" fn(host: *mut FlowHost, decl: *const FlowMediaLinkerDecl) -> FlowStatus,
    pub register_ai_backend:
        unsafe extern "C" fn(host: *mut FlowHost, decl: *const FlowAiBackendDecl) -> FlowStatus,
    pub is_cancelled: unsafe extern "C" fn(host: *mut FlowHost) -> c_int,
    pub log: unsafe extern "C" fn(host: *mut FlowHost, level: c_int, message: *const c_char),
    pub buffer_ref: unsafe extern "C" fn(buffer: *mut FlowBuffer) -> FlowStatus,
    pub buffer_unref: unsafe extern "C" fn(buffer: *mut FlowBuffer),
}

// ---- Effect vtable -------------------------------------------------------

pub type FlowProgressCallback = unsafe extern "C" fn(userdata: *mut c_void, progress: f64);

#[repr(C)]
pub struct FlowEffectVTable {
    pub process: unsafe extern "C" fn(
        effect: *mut FlowEffectHandle,
        inputs: *mut *mut FlowFrame,
        num_inputs: usize,
        outputs: *mut *mut FlowFrame,
        num_outputs: usize,
        progress_cb: Option<FlowProgressCallback>,
        progress_userdata: *mut c_void,
    ) -> FlowStatus,
    pub destroy: unsafe extern "C" fn(effect: *mut FlowEffectHandle),
}

// ---- Safe Rust wrapper (for plugin authors) ------------------------------

/// A safe wrapper around the C ABI, used by plugins written in Rust.
pub struct PluginContext {
    host: *mut FlowHost,
}

impl PluginContext {
    /// # Safety
    /// The host pointer must be valid for the lifetime of this context.
    pub unsafe fn from_raw(host: *mut FlowHost) -> Self {
        Self { host }
    }

    pub fn register_effect(&self, decl: &FlowEffectDecl) -> FlowStatus {
        unsafe {
            let vtable = (*self.host).vtable;
            ((*vtable).register_effect)(self.host, decl as *const _)
        }
    }

    pub fn register_media_linker(&self, decl: &FlowMediaLinkerDecl) -> FlowStatus {
        unsafe {
            let vtable = (*self.host).vtable;
            ((*vtable).register_media_linker)(self.host, decl as *const _)
        }
    }

    pub fn register_ai_backend(&self, decl: &FlowAiBackendDecl) -> FlowStatus {
        unsafe {
            let vtable = (*self.host).vtable;
            ((*vtable).register_ai_backend)(self.host, decl as *const _)
        }
    }

    pub fn is_cancelled(&self) -> bool {
        unsafe {
            let vtable = (*self.host).vtable;
            ((*vtable).is_cancelled)(self.host) != 0
        }
    }
}

// ---- Required entry point macros -----------------------------------------

/// Macro to declare the four required plugin entry points.
///
/// Plugins written in Rust should use this macro to ensure the symbols are
/// exported with the correct names and signatures.
///
/// ```ignore
/// flow_plugin_export!(MyPlugin, my_plugin_info, my_plugin_register);
/// ```
#[macro_export]
macro_rules! flow_plugin_export {
    ($plugin:ident, $info:ident, $register:ident) => {
        #[no_mangle]
        pub extern "C" fn flow_plugin_info() -> $crate::abi::FlowPluginInfo {
            $info()
        }

        #[no_mangle]
        pub extern "C" fn flow_plugin_register(host: *mut $crate::abi::FlowHost) -> $crate::abi::FlowStatus {
            unsafe { $register(host) }
        }

        #[no_mangle]
        pub extern "C" fn flow_plugin_shutdown() {
            // Default: no-op. Plugins can override by exporting their own.
        }
    };
}
