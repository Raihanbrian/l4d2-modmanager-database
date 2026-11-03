"""One atomic Save action reusing M5 validators without nested commits."""

from contextlib import contextmanager
from .classification import save_mod_edit, save_effect_edit
from .storage import CatalogError


def save_details(database, installation_id, *, package_id, mod, effects):
    class TransactionView:
        connection = database.connection
        @contextmanager
        def transaction(self):
            yield self.connection
    with database.transaction() as connection:
        proxy = TransactionView()
        save_mod_edit(proxy,installation_id,package_id,**mod)
        for effect_id,values in effects.items():
            row = connection.execute('SELECT package_id FROM package_effects WHERE effect_id=?',(effect_id,)).fetchone()
            if row is None or row[0] != package_id: raise CatalogError('Effect is outside the selected mod.')
            save_effect_edit(proxy,installation_id,effect_id,**values)
