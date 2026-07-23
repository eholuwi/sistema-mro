"""Pacote ui/ — camada de interface do Sistema MRO (v5.0.0).

Fundação da refatoração faseada (ver docs/PLANO_V5_EVOLUCAO.md). O antigo app.py
monolítico (~4.700 linhas) vira um shell fino que só monta a sidebar e despacha para
o router; cada página vive em ui/paginas/ expondo `def render() -> None`.

Regra de dependência:
- ui/paginas/*  importa ui/componentes|cache|formatos|tema e services/*;
  nunca importa app.py nem outra página.
- services/* NUNCA importa ui/ (a camada de serviço permanece pura e testável).
"""
