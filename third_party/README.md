C headers of whisper.cpp **v1.9.4** (commit 927cfce34f31707e17f2bff35c349632fb9e2c3a), the same commit as the pinned
base image: `parakeet.h`, `whisper.h` and `ggml/*.h` from https://github.com/ggml-org/whisper.cpp (MIT licence, see
`LICENSE.whisper.cpp`). They are not compiled into the server; the ctypes bindings in `wyoming_vulkan/engines/` mirror
their structs, and `tests/check_abi.sh` compiles a layout check against them.

`wyoming_vulkan/hass_api.py` and `wyoming_vulkan/vocabulary.py` are adapted from
OHF-Voice/wyoming-faster-whisper (MIT; `LICENSE.ha-vocabulary`). The Vulkan integration and nonblocking cache
use this project's engine and endpoint interfaces.
Reference checkout: `b03d4e40cf47e67969fe798b8149b62267db0711`.
