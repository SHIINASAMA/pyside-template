import platform


def get_sysname() -> str:
    sysname = platform.system().lower()
    if sysname == "windows":
        return "windows"
    elif sysname == "darwin":
        return "macos"
    elif sysname == "linux":
        return "linux"
    else:
        raise RuntimeError(f"Unknown system: {sysname}")


def get_arch() -> str:
    arch = platform.machine().lower()
    if arch in ("x86_64", "amd64"):
        return "x64"
    elif arch in ("aarch64", "arm64"):
        return "arm64"
    else:
        raise RuntimeError(f"Unknown architecture: {arch}")
