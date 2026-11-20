"""Ordem dos sons e colecoes. Funcoes puras sobre o cfg (sem GUI), testadas em tests/.

- cfg["slots"]: lista de sons; a ordem da lista e a ordem na tela.
- slot["collection"]: nome da colecao do som, ou None (sem colecao).
- cfg["collections"]: [{"name", "collapsed"}] na ordem em que aparecem.

Na tela vem primeiro os sons sem colecao e depois cada colecao com os seus sons.
Os slots sao dicts e dois slots vazios sao iguais (==), por isso a busca e por identidade.
"""


def index(items, obj):
    """Posicao de obj na lista comparando por identidade (list.index compara por ==)."""
    return next(i for i, x in enumerate(items) if x is obj)


def names(cfg):
    return [c["name"] for c in cfg["collections"]]


def find(cfg, name):
    return next((c for c in cfg["collections"] if c["name"] == name), None)


def normalize(cfg):
    """Completa configs antigas ou editadas a mao: campos que faltam, colecoes repetidas
    e sons apontando para uma colecao que nao existe (ela e criada)."""
    cols, seen = [], set()
    for c in cfg.get("collections") or []:
        if isinstance(c, str):
            c = {"name": c}
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            cols.append({"name": name, "collapsed": bool(c.get("collapsed"))})
    cfg["collections"] = cols
    for s in cfg["slots"]:
        s.setdefault("key", "")
        s.setdefault("path", "")
        s.setdefault("volume", 1.0)
        name = str(s.get("collection") or "").strip() or None
        s["collection"] = name
        if name and name not in seen:
            seen.add(name)
            cols.append({"name": name, "collapsed": False})
    return cfg


def groups(cfg):
    """[(colecao ou None, [slots])] na ordem da tela: sons sem colecao e depois cada colecao."""
    out = [(None, [s for s in cfg["slots"] if not s["collection"]])]
    for c in cfg["collections"]:
        out.append((c, [s for s in cfg["slots"] if s["collection"] == c["name"]]))
    return out


def neighbor(cfg, slot, delta):
    """Som vizinho na mesma colecao (delta -1 = acima, +1 = abaixo), ou None na ponta."""
    same = [s for s in cfg["slots"] if s["collection"] == slot["collection"]]
    i = index(same, slot) + delta
    return same[i] if 0 <= i < len(same) else None


def move(cfg, slot, delta):
    """Troca o som de lugar com o vizinho da mesma colecao. Retorna False se ja esta na ponta."""
    other = neighbor(cfg, slot, delta)
    if other is None:
        return False
    slots = cfg["slots"]
    i, j = index(slots, slot), index(slots, other)
    slots[i], slots[j] = slots[j], slots[i]
    return True


def set_collection(cfg, slot, name):
    """Poe o som no fim da colecao name (None = sem colecao). Retorna False se ja estava nela."""
    name = name or None
    if slot["collection"] == name:
        return False
    if name is not None and find(cfg, name) is None:
        raise KeyError(name)
    slots = cfg["slots"]
    slots.pop(index(slots, slot))
    slots.append(slot)
    slot["collection"] = name
    return True


def clean_name(cfg, name, current=None, reserved=()):
    """Valida o nome de uma colecao. Retorna (nome_limpo, erro) com erro None, "empty" ou "exists".

    current: nome atual (ao renomear, pode mudar so maiusculas/minusculas).
    reserved: textos que nao podem virar nome (ex.: o rotulo "(sem colecao)" do menu).
    """
    name = " ".join(str(name or "").split())
    if not name:
        return name, "empty"
    key = name.casefold()
    taken = {n.casefold() for n in names(cfg) if n != current} | {r.casefold() for r in reserved}
    if key in taken:
        return name, "exists"
    return name, None


def add_collection(cfg, name):
    cfg["collections"].append({"name": name, "collapsed": False})


def rename_collection(cfg, old, new):
    find(cfg, old)["name"] = new
    for s in cfg["slots"]:
        if s["collection"] == old:
            s["collection"] = new


def delete_collection(cfg, name):
    """Apaga a colecao; os sons dela vao para o fim dos sons sem colecao (nenhum som e apagado)."""
    cfg["collections"].remove(find(cfg, name))
    moved = [s for s in cfg["slots"] if s["collection"] == name]
    cfg["slots"][:] = [s for s in cfg["slots"] if s["collection"] != name] + moved
    for s in moved:
        s["collection"] = None
    return len(moved)


def move_collection(cfg, name, delta):
    cols = cfg["collections"]
    i = index(cols, find(cfg, name))
    j = i + delta
    if not 0 <= j < len(cols):
        return False
    cols[i], cols[j] = cols[j], cols[i]
    return True


def set_collapsed(cfg, name, collapsed):
    find(cfg, name)["collapsed"] = bool(collapsed)
