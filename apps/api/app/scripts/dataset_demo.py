from app.db.session import get_session_factory
from app.models import Dataset, DatasetVersion




with get_session_factory()() as session:
    dataset = Dataset(name="Sales")
    session.add(dataset)
    session.flush()

    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=1,
        original_filename='sales.csv',
        file_format='csv',
        storage_bucket='data-notebook-dev',
        original_object_key='random_key',
    )

    session.add(version)
    session.commit()