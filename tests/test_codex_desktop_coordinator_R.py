"""Coordinator routing for desktop Codex, without a live queue or real sessions."""
import pytest
import sessions as ses

from lienzo import server


@pytest.fixture(params=['codex', 'claude'])
def card(monkeypatch, request):
    agent = request.param
    item = ses.new_session('desktop-fixture', agent, 'desktop')
    item.update(repo='fixture-repo', repo_key='fixture-repo', alive=True, no_console=True,
                external={'kind': agent + '-desktop', 'via': 'rollout', 'desktop': True})
    monkeypatch.setattr(ses, 'sessions', {item['session_id']: item})
    monkeypatch.setattr(server, 'sessions', ses.sessions)
    monkeypatch.setattr(server, '_route_session', lambda sid: (item, None))
    monkeypatch.setattr(ses, '_mirror_sessions', list)
    monkeypatch.setattr(ses, 'touch', lambda s: None)
    return item


def request(card, on):
    return server.atender_accion('PUT', card['session_id'], 'coordinator', {'on': on}, desde_tablero=True)


def test_desktop_can_become_coordinator_when_queue_is_usable(card, monkeypatch):
    monkeypatch.setattr(ses, 'puede_enviar', lambda s: {'puede': True})
    code, body = request(card, True)
    assert code == 200 and body['coordinator'] is True and card['coordinator'] is True


def test_unusable_queue_keeps_role_disabled(card, monkeypatch):
    plan = {'puede': False, 'motivo': 'app cerrada', 'transporte': None}
    monkeypatch.setattr(ses, 'puede_enviar', lambda s: plan)
    code, body = request(card, True)
    assert code == 409 and body['envio'] == plan and card['coordinator'] is False


def test_role_remains_unique_within_repo(card, monkeypatch):
    previous = dict(card, session_id='previous', coordinator=True)
    ses.sessions['previous'] = previous
    monkeypatch.setattr(ses, 'puede_enviar', lambda s: {'puede': True})
    assert request(card, True)[0] == 200
    assert card['coordinator'] is True and previous['coordinator'] is False


def test_role_can_be_removed_after_queue_disappears(card, monkeypatch):
    card['coordinator'] = True
    monkeypatch.setattr(ses, 'puede_enviar', lambda s: pytest.fail('revocation must not need delivery'))
    code, body = request(card, False)
    assert code == 200 and body['coordinator'] is False


@pytest.mark.parametrize('kind,agent', [('batch', 'codex'), ('orquestador', 'codex'),
                                        ('claude-desktop', 'codex'), ('codex-desktop', 'claude')])
def test_other_external_cards_remain_restricted(card, monkeypatch, kind, agent):
    card.update(agent=agent, external={'kind': kind, 'desktop': True})
    monkeypatch.setattr(ses, 'puede_enviar', lambda s: pytest.fail('unsupported external card'))
    assert request(card, True)[0] == 409
    assert card['coordinator'] is False


@pytest.mark.parametrize('action', ['interrupt', 'kill', 'stopped', 'approve', 'native'])
def test_role_exception_does_not_enable_console_control(card, monkeypatch, action):
    monkeypatch.setattr(ses, 'puede_enviar', lambda s: {'puede': True})
    method = 'PUT' if action == 'stopped' else 'POST'
    body = {'decision': 'allow'} if action == 'approve' else {'on': True}
    code, _ = server.atender_accion(method, card['session_id'], action, body, desde_tablero=True)
    assert code == 409


def test_validation_still_rejects_non_boolean(card):
    assert request(card, 'yes')[0] == 400
