"""Explicit administrator-only adoption of ownerless pre-authentication demo data."""

import argparse
from uuid import UUID

from app.db.session import get_session_factory
from app.models import Dataset, DatasetVersion, Notebook, NotebookCell, User
from sqlalchemy import select


def assign(user_id: UUID, apply: bool = False):
    with get_session_factory()() as session:
        if session.get(User, user_id) is None:
            raise ValueError("User not found. Sign in first and use the id from /api/v1/auth/me.")
        datasets = session.scalars(
            select(Dataset).where(Dataset.owner_id.is_(None)).with_for_update()
        ).all()
        notebooks = session.scalars(
            select(Notebook).where(Notebook.owner_id.is_(None)).with_for_update()
        ).all()
        if notebooks:
            owners = session.scalars(
                select(Dataset.owner_id)
                .join(DatasetVersion)
                .join(NotebookCell)
                .where(NotebookCell.notebook_id.in_([n.id for n in notebooks]))
            ).all()
            if any(owner is not None and owner != user_id for owner in owners):
                raise ValueError(
                    "A legacy notebook refers to another user's dataset. Review manually."
                )
        print(
            f"Ownerless datasets: {len(datasets)}; ownerless notebooks: {len(notebooks)}; target user: {user_id}"
        )
        if apply:
            for resource in [*datasets, *notebooks]:
                resource.owner_id = user_id
            session.commit()
            print("Assigned legacy records. Existing owners were unchanged.")
        else:
            print("Preview only. Add --apply to assign these records.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    assign(args.user_id, args.apply)


if __name__ == "__main__":
    main()
