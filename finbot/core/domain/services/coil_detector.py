"""Stub — not yet copied from Finbar. Raises NotImplementedError if called."""


def _not_implemented(*_args, **_kwargs):
    raise NotImplementedError(
        "This domain service has not been copied from Finbar yet. "
        "It is not required by the AMT target strategies."
    )


# Re-export commonly referenced symbols as stubs.
__all__: list[str] = []
detect_coil = _not_implemented
