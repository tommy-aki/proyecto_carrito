from carrito_smart.database import Database
from scripts.check_fusion_hardware import copy_database


def test_hardware_snapshot_is_independent_and_releases_file_handles(tmp_path):
    source = Database(tmp_path / "source.db")
    source.initialize()
    target = Database(tmp_path / "snapshot.db")
    copy_database(source.path, target.path)
    with target.connect() as connection:
        connection.execute("UPDATE products SET stock=0")
        connection.commit()
    assert source.get_product_by_sku("CS-001").stock == 100
    assert target.get_product_by_sku("CS-001").stock == 0
    target.path.unlink()  # Solo la copia descartable del directorio pytest.
