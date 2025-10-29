try:
    from .audiopipewire import AudioPipeWire  # noqa: F401

    HAS_PIPEWIRE = True
except ImportError:
    HAS_PIPEWIRE = False
