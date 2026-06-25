"""Item 3 (v2.1.0): formulário de sugestões/feedback (registrar, listar, atualizar)."""
from services import db_functions as F


def test_registrar_feedback_status_novo(db):
    ok, msg = F.registrar_feedback("Relato de bug", "Erro ao salvar",
                                   "passos para reproduzir", autor="luis",
                                   pagina_origem="Inventário")
    assert ok, msg
    fbs = F.listar_feedbacks()
    assert len(fbs) == 1
    assert fbs[0]["status"] == "Novo"
    assert fbs[0]["tipo"] == "Relato de bug"


def test_registrar_exige_tipo_e_titulo(db):
    assert F.registrar_feedback("", "titulo")[0] is False
    assert F.registrar_feedback("Relato de bug", "")[0] is False


def test_filtra_por_tipo(db):
    F.registrar_feedback("Relato de bug", "b1")
    F.registrar_feedback("Melhoria de UX", "u1")
    assert len(F.listar_feedbacks(tipo="Relato de bug")) == 1
    assert len(F.listar_feedbacks(tipo="Todos")) == 2


def test_atualizar_status_persiste(db):
    F.registrar_feedback("Relato de bug", "b")
    fid = F.listar_feedbacks()[0]["id"]
    ok, _ = F.atualizar_feedback(fid, status="Em análise", prioridade="Alta")
    assert ok
    fb = F.listar_feedbacks()[0]
    assert fb["status"] == "Em análise"
    assert fb["prioridade"] == "Alta"
