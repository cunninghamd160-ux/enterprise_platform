<%!
    def literal(value):
        if value is None:
            return "None"
        if isinstance(value, str):
            return '"' + value + '"'
        return "(" + "".join('"' + item + '", ' for item in value) + ")"
%>\
<%
    body = (upgrades or "") + (downgrades or "")
    uses_sa = "sa." in body
    uses_op = "op." in body
%>\
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from collections.abc import Sequence
% if uses_sa or uses_op or imports:

% endif
% if uses_sa:
import sqlalchemy as sa
% endif
% if uses_op:
from alembic import op
% endif
% if imports:
${imports}
% endif

revision: str = ${literal(up_revision)}
down_revision: str | Sequence[str] | None = ${literal(down_revision)}
branch_labels: str | Sequence[str] | None = ${literal(branch_labels)}
depends_on: str | Sequence[str] | None = ${literal(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
