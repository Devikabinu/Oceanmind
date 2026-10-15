"""species catalogue, alert details, species columns on biodiversity observations

Revision ID: 7c1d9e3a5b21
Revises: 50a78b589646
Create Date: 2026-10-14 22:00:00

Additive only: one new table and four nullable columns. No existing data is touched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7c1d9e3a5b21"
down_revision: Union[str, None] = "50a78b589646"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "species",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("aphia_id", sa.Integer(), nullable=False),
        sa.Column("scientific_name", sa.String(length=255), nullable=False),
        sa.Column("common_name", sa.String(length=255), nullable=True),
        sa.Column("taxon_group", sa.String(length=50), nullable=False),
        sa.Column("class_name", sa.String(length=100), nullable=True),
        sa.Column("order_name", sa.String(length=100), nullable=True),
        sa.Column("family", sa.String(length=100), nullable=True),
        sa.Column("iucn_category", sa.String(length=10), nullable=True),
        sa.Column("iucn_source", sa.String(length=255), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("watchlist", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_species_aphia_id"), "species", ["aphia_id"], unique=True)
    op.create_index(op.f("ix_species_scientific_name"), "species", ["scientific_name"], unique=False)
    op.create_index(op.f("ix_species_taxon_group"), "species", ["taxon_group"], unique=False)
    op.create_index(op.f("ix_species_iucn_category"), "species", ["iucn_category"], unique=False)

    op.add_column("alerts", sa.Column("details", sa.JSON(), nullable=True))

    op.add_column("biodiversity_observations", sa.Column("species_name", sa.String(length=255), nullable=True))
    op.add_column("biodiversity_observations", sa.Column("species_aphia_id", sa.Integer(), nullable=True))
    op.add_column("biodiversity_observations", sa.Column("taxon_class", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_biodiversity_observations_species_name"), "biodiversity_observations", ["species_name"], unique=False)
    op.create_index(op.f("ix_biodiversity_observations_species_aphia_id"), "biodiversity_observations", ["species_aphia_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_biodiversity_observations_species_aphia_id"), table_name="biodiversity_observations")
    op.drop_index(op.f("ix_biodiversity_observations_species_name"), table_name="biodiversity_observations")
    op.drop_column("biodiversity_observations", "taxon_class")
    op.drop_column("biodiversity_observations", "species_aphia_id")
    op.drop_column("biodiversity_observations", "species_name")
    op.drop_column("alerts", "details")
    op.drop_index(op.f("ix_species_iucn_category"), table_name="species")
    op.drop_index(op.f("ix_species_taxon_group"), table_name="species")
    op.drop_index(op.f("ix_species_scientific_name"), table_name="species")
    op.drop_index(op.f("ix_species_aphia_id"), table_name="species")
    op.drop_table("species")
