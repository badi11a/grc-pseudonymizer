from typing import Callable

from fastfpe import ff1


def make_cifrar(cfg: dict) -> Callable[[int | str], str]:
    key = cfg["fpe"]["key"]
    tweak = cfg["fpe"]["tweak"]
    alphabet = cfg["fpe"]["alphabet"]

    def cifrar(valor: int | str) -> str:
        return ff1.encrypt(key, tweak, alphabet, str(valor).zfill(6))

    return cifrar
