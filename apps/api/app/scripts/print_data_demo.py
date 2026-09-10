from app.db.session import get_session_factory
from app.models import Dataset, DatasetVersion
from sqlalchemy import select

with get_session_factory()() as session:
    datasets = session.scalars(
        select(Dataset).where(Dataset.name == "Sales")
    ).all()

    for dataset in datasets:
        print(dataset.id, dataset.name)
        for version in dataset.versions:
            print(version.version_number, version.status)