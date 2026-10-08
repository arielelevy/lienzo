"""Cuenta de GitHub por repo (2026-10-08): gh solo sirve la credencial de la cuenta activa, asi que
cada repo de github.com con sesion viva queda fijado en su .git/config a la cuenta con push."""

import subprocess

import cuenta_github as cg
import health
import pytest

STATUS_GH = """github.com
  ✓ Logged in to github.com account ariel-levy_globant (keyring)
  - Active account: true
  - Git operations protocol: https
  - Token: gho_************************************
  - Token scopes: 'gist', 'read:org', 'repo', 'workflow'

  ✓ Logged in to github.com account arielelevy (keyring)
  - Active account: false
  - Git operations protocol: https

  ✓ Logged in to github.com account arieledgardolevy (keyring)
  - Active account: false
"""


@pytest.fixture(autouse=True)
def _sin_decisiones():
    cg.olvidar()
    yield
    cg.olvidar()


def test_duenio_y_repo_solo_https_de_github():
    assert cg.duenio_y_repo("https://github.com/arielelevy/lienzo.git") == ("arielelevy", "lienzo")
    assert cg.duenio_y_repo("https://github.com/arielelevy/lienzo") == ("arielelevy", "lienzo")
    assert cg.duenio_y_repo("https://github.com/Org-X/mi.repo/") == ("Org-X", "mi.repo")
    assert cg.duenio_y_repo("https://usuario@github.com/o/r.git") == ("o", "r")
    assert cg.duenio_y_repo("git@github.com:o/r.git") is None  # ssh va con llaves
    assert cg.duenio_y_repo("https://dev.azure.com/org/proj/_git/r") is None
    assert cg.duenio_y_repo("https://github.com/o") is None
    assert cg.duenio_y_repo("https://github.com/o/r/extra") is None
    assert cg.duenio_y_repo(None) is None


def test_cuentas_parsea_el_status_de_gh_con_la_activa(monkeypatch):
    monkeypatch.setattr(cg, "_gh", lambda args, env=None, timeout=0: (1, "", STATUS_GH))
    assert cg.cuentas() == (["ariel-levy_globant", "arielelevy", "arieledgardolevy"], "ariel-levy_globant")
    monkeypatch.setattr(cg, "_gh", lambda args, env=None, timeout=0: (0, STATUS_GH, ""))  # por stdout tambien
    assert cg.cuentas()[1] == "ariel-levy_globant"


def test_cuentas_salta_una_cuenta_que_fallo_y_no_le_cuelga_la_activa_a_la_anterior(monkeypatch):
    """Code review 2026-10-08: «X Failed to log in to github.com account B» seguido de «Active
    account: true» dejaba a la cuenta anterior como activa."""
    salida = """  ✓ Logged in to github.com account a (keyring)
  - Active account: false
  X Failed to log in to github.com account b (keyring)
  - Active account: true
"""
    monkeypatch.setattr(cg, "_gh", lambda args, env=None, timeout=0: (1, "", salida))
    assert cg.cuentas() == (["a"], None)


def test_cuentas_se_cachea_un_minuto_y_un_vacio_no(monkeypatch):
    """`gh auth status` valida cada token contra la API: no se repite por cada url ni cada vuelta."""
    veces = []
    monkeypatch.setattr(cg, "_gh", lambda args, env=None, timeout=0: (veces.append(1), (1, "", STATUS_GH))[1])
    assert cg.cuentas(ahora=100)[1] == "ariel-levy_globant"
    assert cg.cuentas(ahora=130)[1] == "ariel-levy_globant"
    assert len(veces) == 1
    cg.cuentas(ahora=100 + cg.CUENTAS_TTL_S + 1)
    assert len(veces) == 2
    cg.olvidar()
    monkeypatch.setattr(cg, "_gh", lambda args, env=None, timeout=0: (cg.subproc.VENCIDO, "", "lento"))
    assert cg.cuentas(ahora=500) == ([], None)
    assert cg.cuentas(ahora=501) == ([], None) and len(veces) == 2  # no se cacheo: se vuelve a preguntar


def test_gh_corre_sin_el_token_heredado_del_entorno(monkeypatch):
    """Con GH_TOKEN en el entorno del server, `gh auth token --user X` devuelve ese para cualquier X."""
    envs = []
    monkeypatch.setattr(cg.subproc, "correr", lambda argv, **k: (envs.append(k.get("env")), (1, "", ""))[1])
    cg._gh(["auth", "status"])
    assert envs[0]["GH_TOKEN"] == "" and envs[0]["GITHUB_TOKEN"] == ""
    assert "GH_TOKEN= GITHUB_TOKEN= gh auth token" in cg.helper_de("a")


def test_cuentas_sin_gh_o_sin_login(monkeypatch):
    monkeypatch.setattr(cg, "_gh", lambda args, env=None, timeout=0: (cg.subproc.NO_ARRANCO, "", "no esta"))
    assert cg.cuentas() == ([], None)
    monkeypatch.setattr(
        cg, "_gh", lambda args, env=None, timeout=0: (1, "", "You are not logged into any GitHub hosts")
    )
    assert cg.cuentas() == ([], None)


def test_elegir_prueba_primero_la_duenia_despues_la_activa_y_se_queda_con_la_primera_con_push():
    probadas = []

    def probar(cuenta, duenio, repo):
        probadas.append(cuenta)
        return cuenta == "arielelevy"

    logins = ["ariel-levy_globant", "arielelevy", "arieledgardolevy"]
    assert cg.elegir("https://github.com/arielelevy/lienzo.git", logins, "ariel-levy_globant", probar) == "arielelevy"
    assert probadas == ["arielelevy"]  # la que se llama como el dueño va primero y alcanzo
    probadas.clear()
    assert (
        cg.elegir(
            "https://github.com/smartbi/x.git", logins, "arieledgardolevy", lambda c, d, r: c == "ariel-levy_globant"
        )
        == "ariel-levy_globant"
    )


def test_elegir_none_si_ninguna_tiene_push_o_no_se_pudo_saber():
    logins = ["a", "b"]
    assert cg.elegir("https://github.com/o/r", logins, "a", lambda c, d, r: False) is None
    assert cg.elegir("https://github.com/o/r", logins, "a", lambda c, d, r: None) is None
    assert cg.elegir("https://github.com/o/r", [], None, lambda c, d, r: True) is None
    assert cg.elegir("https://dev.azure.com/o/p/_git/r", logins, "a", lambda c, d, r: True) is None


def test_tiene_push_consulta_la_api_con_el_token_de_esa_cuenta_y_no_lo_filtra(monkeypatch):
    llamadas = []

    def gh(args, env=None, timeout=0):
        llamadas.append((args, env))
        if args[:2] == ["auth", "token"]:
            return 0, "gho_secreto\n", ""
        return 0, "true\n", ""

    monkeypatch.setattr(cg, "_gh", gh)
    assert cg.tiene_push("arielelevy", "arielelevy", "lienzo") is True
    assert llamadas[0][0] == ["auth", "token", "--user", "arielelevy", "--hostname", "github.com"]
    assert llamadas[1][0][:2] == ["api", "repos/arielelevy/lienzo"]
    assert llamadas[1][1] == {"GH_TOKEN": "gho_secreto"}


def test_tiene_push_false_sin_permiso_y_none_sin_red_o_sin_token(monkeypatch):
    def gh_con(api):
        def gh(args, env=None, timeout=0):
            return (0, "tok", "") if args[0] == "auth" else api

        return gh

    monkeypatch.setattr(cg, "_gh", gh_con((0, "false\n", "")))
    assert cg.tiene_push("a", "o", "r") is False
    monkeypatch.setattr(cg, "_gh", gh_con((1, "", "gh: Not Found (HTTP 404)")))
    assert cg.tiene_push("a", "o", "r") is False
    monkeypatch.setattr(cg, "_gh", gh_con((1, "", "error connecting to api.github.com")))
    assert cg.tiene_push("a", "o", "r") is None
    monkeypatch.setattr(cg, "_gh", lambda args, env=None, timeout=0: (1, "", "no such user"))
    assert cg.tiene_push("a", "o", "r") is None
    assert cg.tiene_push("a b", "o", "r") is None  # un login invalido no llega a gh


def test_helper_de_saca_el_token_al_usarlo_y_rechaza_logins_raros():
    h = cg.helper_de("arielelevy")
    assert h.startswith("!") and "gh auth token --user arielelevy --hostname github.com" in h
    assert "username=arielelevy" in h and '"$1" = get' in h
    with pytest.raises(ValueError):
        cg.helper_de("x; rm -rf /")


def _repo(tmp_path):
    d = tmp_path / "repo" if tmp_path.name not in ("a", "b") else tmp_path
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    return str(d)


def test_fijar_deja_helper_vacio_mas_el_de_la_cuenta_solo_para_github_y_es_idempotente(tmp_path):
    repo = _repo(tmp_path)
    assert cg.cuenta_fijada(repo) is None
    assert cg.fijar(repo, "arielelevy")
    assert cg.cuenta_fijada(repo) == "arielelevy"
    assert cg.fijar(repo, "ariel-levy_globant")
    assert cg.cuenta_fijada(repo) == "ariel-levy_globant"
    out = subprocess.run(
        ["git", "config", "--local", "--get-all", cg.CLAVE_HELPER], cwd=repo, capture_output=True, text=True
    ).stdout.splitlines()
    assert len(out) == 2 and out[0] == "" and "ariel-levy_globant" in out[1]
    # lo global no se toca y no queda nada fuera del alcance github.com
    assert (
        subprocess.run(
            ["git", "config", "--local", "--get-all", "credential.helper"], cwd=repo, capture_output=True, text=True
        ).stdout
        == ""
    )


def test_asegurar_fija_la_cuenta_con_push_y_despues_no_vuelve_a_preguntar(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    url = "https://github.com/arielelevy/lienzo.git"
    monkeypatch.setattr(cg, "cuentas", lambda: (["ariel-levy_globant", "arielelevy"], "ariel-levy_globant"))
    probadas = []
    monkeypatch.setattr(cg, "tiene_push", lambda c, d, r: probadas.append(c) or c == "arielelevy")
    avisos = []
    monkeypatch.setattr(cg, "log", avisos.append)
    assert cg.asegurar(repo, url) == "arielelevy"
    assert cg.cuenta_fijada(repo) == "arielelevy"
    assert probadas == ["arielelevy"] and "fijado a la cuenta arielelevy" in avisos[0]
    assert cg.asegurar(repo, url) == "arielelevy"
    assert probadas == ["arielelevy"]  # ya fijado a una cuenta que gh tiene: ni API ni log
    assert len(avisos) == 1


def test_asegurar_con_forzar_vuelve_a_elegir_y_cambia_si_corresponde(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    url = "https://github.com/smartbi/x.git"
    monkeypatch.setattr(cg, "cuentas", lambda: (["ariel-levy_globant", "arielelevy"], "arielelevy"))
    cg.fijar(repo, "arielelevy")  # quedo fijado a una que perdio el permiso
    monkeypatch.setattr(cg, "tiene_push", lambda c, d, r: c == "ariel-levy_globant")
    assert cg.asegurar(repo, url) == "arielelevy"  # sin forzar, se respeta lo fijado
    assert cg.asegurar(repo, url, forzar=True) == "ariel-levy_globant"
    assert cg.cuenta_fijada(repo) == "ariel-levy_globant"


def test_una_forzada_que_no_encontro_nada_mejor_no_se_repite_hasta_el_ttl(tmp_path, monkeypatch):
    """Code review 2026-10-08: con el token vencido de verdad, cada vuelta de health (cada 5 min)
    volvia a preguntar a la API por todas las cuentas."""
    repo = _repo(tmp_path)
    url = "https://github.com/o/r.git"
    monkeypatch.setattr(cg, "cuentas", lambda: (["a", "b"], "a"))
    cg.fijar(repo, "a")
    probadas = []
    monkeypatch.setattr(cg, "tiene_push", lambda c, d, r: probadas.append(c) or False)
    assert cg.asegurar(repo, url, forzar=True) == "a"
    assert probadas == ["a", "b"]
    assert cg.asegurar(repo, url, forzar=True) == "a"
    assert probadas == ["a", "b"]  # hace poco se volvio a elegir: no se insiste
    monkeypatch.setattr(cg, "REELECCION_TTL_S", 0)
    assert cg.asegurar(repo, url, forzar=True) == "a"
    assert probadas == ["a", "b", "a", "b"]


def test_si_no_se_pudo_escribir_el_config_queda_la_cuenta_de_antes(tmp_path, monkeypatch):
    """Code review 2026-10-08: asegurar devolvia la elegida aunque `git config` fallara (config.lock
    tomado) y health volvia a medir con el helper viejo."""
    repo = _repo(tmp_path)
    url = "https://github.com/o/r.git"
    monkeypatch.setattr(cg, "cuentas", lambda: (["a", "b"], "a"))
    cg.fijar(repo, "a")
    monkeypatch.setattr(cg, "tiene_push", lambda c, d, r: c == "b")
    monkeypatch.setattr(cg, "fijar", lambda r, c: False)
    assert cg.asegurar(repo, url, forzar=True) == "a"
    assert cg.cuenta_fijada(repo) == "a"


def test_fijado_a_una_cuenta_que_gh_ya_no_tiene_se_vuelve_a_elegir(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    url = "https://github.com/o/r.git"
    cg.fijar(repo, "vieja")
    monkeypatch.setattr(cg, "cuentas", lambda: (["a"], "a"))
    monkeypatch.setattr(cg, "tiene_push", lambda c, d, r: True)
    assert cg.asegurar(repo, url) == "a"
    assert cg.cuenta_fijada(repo) == "a"


def test_asegurar_no_toca_el_repo_sin_red_sin_gh_o_fuera_de_github(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    url = "https://github.com/o/r.git"
    monkeypatch.setattr(cg, "cuentas", lambda: (["a", "b"], "a"))
    monkeypatch.setattr(cg, "tiene_push", lambda c, d, r: None)  # sin red
    assert cg.asegurar(repo, url) is None
    assert cg.cuenta_fijada(repo) is None
    monkeypatch.setattr(cg, "cuentas", lambda: ([], None))  # sin gh
    assert cg.asegurar(repo, url) is None
    assert cg.asegurar(repo, "https://dev.azure.com/o/p/_git/r") is None
    assert cg.asegurar(None, url) is None
    assert cg.asegurar(str(tmp_path / "no-existe"), url) is None


def test_asegurar_nunca_levanta(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(cg, "cuentas", lambda: 1 / 0)
    avisos = []
    monkeypatch.setattr(cg, "log", avisos.append)
    assert cg.asegurar(repo, "https://github.com/o/r") is None
    assert "ZeroDivisionError" in avisos[0]


def test_health_fija_la_cuenta_antes_de_medir_y_reintenta_si_dio_vencida(tmp_path, monkeypatch):
    """El 403 por cuenta equivocada: health lo ve como «vencida», fuerza otra eleccion y mide de nuevo."""
    repo = _repo(tmp_path)
    url = "https://github.com/arielelevy/lienzo.git"
    monkeypatch.setattr(health, "repos_de_remote", lambda u: [repo])
    fijada = ["ariel-levy_globant"]
    llamadas = []

    def asegurar(r, u, forzar=False):
        llamadas.append(forzar)
        if forzar:
            fijada[0] = "arielelevy"
        return fijada[0]

    monkeypatch.setattr(cg, "asegurar", asegurar)
    monkeypatch.setattr(cg, "cuenta_fijada", lambda r: fijada[0])
    medidas = iter(["vencida", "ok"])
    monkeypatch.setattr(health, "_ls_remote", lambda u, timeout_s=20, cwd=None: next(medidas))
    assert health._medir_git([url]) == {url: "ok"}
    assert llamadas == [False, True]


def test_health_fija_todas_las_carpetas_vivas_con_ese_origin(tmp_path, monkeypatch):
    """Code review 2026-10-08: una segunda copia o worktree del mismo repo quedaba con el helper global."""
    a, b = _repo(tmp_path / "a"), _repo(tmp_path / "b")
    url = "https://github.com/o/r.git"
    monkeypatch.setattr(health, "repos_de_remote", lambda u: [a, b, a, str(tmp_path / "no")])
    fijadas = []
    monkeypatch.setattr(cg, "asegurar", lambda r, u, forzar=False: fijadas.append((r, forzar)) or "x")
    monkeypatch.setattr(cg, "cuenta_fijada", lambda r: "x")
    cwds = []
    monkeypatch.setattr(health, "_ls_remote", lambda u, timeout_s=20, cwd=None: cwds.append(cwd) or "ok")
    assert health._medir_git([url]) == {url: "ok"}
    assert fijadas == [(a, False), (b, False)] and cwds == [a]


def test_health_no_reintenta_si_forzar_no_cambio_la_cuenta(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    url = "https://github.com/o/r.git"
    monkeypatch.setattr(health, "repos_de_remote", lambda u: [repo])
    monkeypatch.setattr(cg, "asegurar", lambda r, u, forzar=False: "a")
    monkeypatch.setattr(cg, "cuenta_fijada", lambda r: "a")
    veces = []
    monkeypatch.setattr(health, "_ls_remote", lambda u, timeout_s=20, cwd=None: veces.append(cwd) or "vencida")
    assert health._medir_git([url]) == {url: "vencida"}
    assert veces == [repo]


def test_health_sin_repo_vivo_mide_en_carpeta_neutra_y_no_llama_a_gh(monkeypatch):
    monkeypatch.setattr(health, "repos_de_remote", lambda u: [])
    monkeypatch.setattr(cg, "asegurar", lambda *a, **k: 1 / 0)
    monkeypatch.setattr(health, "_ls_remote", lambda u, timeout_s=20, cwd=None: "ok")
    assert health._medir_git(["https://github.com/o/r"]) == {"https://github.com/o/r": "ok"}
