# Upstream attribution

This project is a Linux desktop port of [Junming-Liang/coindex](https://github.com/Junming-Liang/coindex), based on upstream commit `61f4dda24b598c920781d6261a8bd252ee4d3dc6` (upstream v1.9.0).

The upstream MIT license and copyright notice remain in [LICENSE](LICENSE). The Python backend, task semantics, Swift sources, original cat artwork, and macOS documentation originate from that project. The Linux Qt interface, Linux platform adapters, wheel packaging, installation scripts, and Linux CI were added by this port.

The original macOS build remains available through `scripts/build.sh`. This repository does not claim to be the upstream project's official Linux distribution. Linux changes preserve the stored `mac` identifier for the local source, so existing task and conversation associations are not renamed.

Public Linux builds include only the upstream public app icon and original `coindex-cat` artwork. Assets optionally imported from a local Codex installation are excluded by the public-file inventory and release checks.
