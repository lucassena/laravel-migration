import glob
import datetime
import traceback
from wb import DefineModule, wbinputs
import grt
import mforms
from workbench.ui import WizardForm, WizardPage
from mforms import newButton, newCodeEditor, FileChooser

migrations = {}  # Global variable to store migrations
migration_tables = {}  # Associating schema -> tables

# Mapping MySQL types to Laravel types
types_map = {
    'BIG_INCREMENTS': 'bigIncrements', 'MEDIUM_INCREMENTS': 'mediumIncrements', 'SMALL_INCREMENTS': 'smallIncrements', 'TINY_INCREMENTS': 'tinyIncrements', 'INCREMENTS': 'increments',
    'TINYINT': 'tinyInteger', 'UNSIGNED_TINYINT': 'unsignedTinyInteger', 
    'SMALLINT': 'smallInteger', 'UNSIGNED_SMALLINT': 'unsignedSmallInteger', 
    'MEDIUMINT': 'mediumInteger', 'UNSIGNED_MEDIUMINT': 'unsignedMediumInteger', 'MIDDLEINT': 'mediumInteger', 
    'INT': 'integer', 'UNSIGNED_INT': 'unsignedInteger', 'INTEGER': 'integer', 'UNSIGNED_INTEGER': 'unsignedInteger',
    'BIGINT': 'bigInteger', 'UNSIGNED_BIGINT': 'unsignedBigInteger',
    'FLOAT': 'float', 'DOUBLE': 'double', 'DECIMAL': 'decimal', 'NUMERIC': 'decimal', 'DEC': 'decimal',
    'JSON': 'json',
    'CHAR': 'char', 'CHARACTER': 'char', 'VARCHAR': 'string', 
    'BINARY': 'binary', 'TINYBLOB': 'binary', 'BLOB': 'binary', 'MEDIUMBLOB': 'binary', 'LONGBLOB': 'binary',
    'TINYTEXT': 'text', 'TEXT': 'text', 'MEDIUMTEXT': 'mediumText', 'LONGTEXT': 'longText',
    'DATETIME': 'dateTime', 'DATE': 'date', 'YEAR': 'year', 'TIME': 'time', 'TIMESTAMP': 'timestamp', 
    'ENUM': 'enum', 'SET': 'set',
    'BOOLEAN': 'boolean', 'BOOL': 'boolean',
    'UUID': 'uuid',
    'MORPHS': 'morphs', 'NULLABLE_MORPHS': 'nullableMorphs',
    'REMEMBER_TOKEN': 'rememberToken',
    'GEOMETRY': 'geometry'
}

# Module information
ModuleInfo = DefineModule(name='LaravelMigration', author='Lucas Martins', version='0.9')

@ModuleInfo.plugin(
    'wb.util.laravel_migration',
    caption='Export Laravel Migration',
    input=[wbinputs.currentCatalog()],
    groups=['Catalog/Utilities', 'Menu/Catalog'],
    pluginMenu='Catalog'
)
@ModuleInfo.export(grt.INT, grt.classes.db_Catalog)

def laravel_migration(catalog):
    """ Generates Laravel migrations from the Workbench model """
    
    # Validação inicial do catálogo
    if not hasattr(catalog, "schemata") or not catalog.schemata:
        mforms.Utilities.show_error("Error", "No schema found in the model. Check your database!", "OK", "", "")
        return 1
    
    try:
        schema_sql_dict = {}
        
        for schema in catalog.schemata:
            if not hasattr(schema, "tables") or not schema.tables:
                mforms.Utilities.show_error("Error", f"Schema '{schema.name}' has no tables!", "OK", "", "")
                continue
            
            print(f"Processing schema: {schema.name}")

            validate_column_sizes(schema)
            
            migrations[schema.name] = {}  
            migration_tables[schema.name] = []

            export_schema(schema)

            print(f"Debug: Migrations generated for {schema.name}: {migrations[schema.name].keys()}")

            # Concatenates all migrations of this schema for display in the UI
            schema_sql_dict[schema.name] = "\n\n".join(migrations[schema.name].values())

    except Exception as e:
        error_message = f"Error generating migrations: {str(e)}\n{traceback.format_exc()}"
        print(error_message)
        mforms.Utilities.show_error("Error", error_message, "OK", "", "")
        return 1
    
    wizard = LaravelMigrationWizard("Laravel Migration Wizard", schema_sql_dict)
    wizard.run()

    return 0

def validate_column_sizes(schema):
    """ Validates if there are VARCHAR columns too large to be UNIQUE """
    warnings = []
    for table in schema.tables:
        for index in table.indices:
            if index.indexType == "UNIQUE":
                for column in index.columns:
                    col = column.referencedColumn
                    if col.simpleType and col.simpleType.name == "VARCHAR":
                        column_size = col.length
                        charset_bytes = 4  # utf8mb4 uses 4 bytes per character
                        total_bytes = column_size * charset_bytes
                        
                        max_bytes = 767 if total_bytes <= 767 else 3072  # MySQL limits

                        if total_bytes > max_bytes:
                            warnings.append(f"Table `{table.name}`, column `{col.name}` (VARCHAR({column_size})) "
                                            f"exceeds the maximum allowed size for UNIQUE indexes ({max_bytes} bytes).")

    if warnings:
        warning_message = "\n".join(warnings)
        mforms.Utilities.show_error(
            "Warning: Invalid Index Size",
            f"The following UNIQUE indexes may cause errors in Laravel:\n\n{warning_message}\n\n"
            "Suggestions:\n"
            "- Reduce the size of the VARCHAR (e.g., `VARCHAR(191)`)\n"
            "- Configure `Schema::defaultStringLength(191);` in Laravel.\n"
            "- Use another collation (`utf8` instead of `utf8mb4`).",
            "OK", "", ""
        )

def order_tables(schema):
    dependencies = {table.name: set() for table in schema.tables}

    for table in schema.tables:
        for fk in table.foreignKeys:
            referenced_table = fk.referencedColumns[0].owner.name
            if referenced_table != table.name:  # Avoid self-dependencies
                dependencies[table.name].add(referenced_table)

    # Function to perform topological sorting
    def topological_sort(dependencies):
        sorted_tables = []
        remaining = dependencies.copy()

        while remaining:
            acyclic = [t for t, refs in remaining.items() if not refs]
            if not acyclic:
                raise Exception("Error: Cycle detected among foreign key tables!")

            sorted_tables.extend(acyclic)

            # Remove the already sorted tables from the dependencies
            for table in acyclic:
                del remaining[table]

            for refs in remaining.values():
                refs.difference_update(acyclic)

        return sorted_tables
    
    # Sorting the tables to ensure that referenced tables are created first
    try:
        ordered_tables = topological_sort(dependencies)
    except Exception as e:
        print(f"Warning: Cyclic dependency detected: {str(e)}")
        ordered_tables = list(dependencies.keys())  # As a fallback, process tables in arbitrary order

    print(f"Debug: Order of processed tables: {ordered_tables}")

    return ordered_tables

def export_schema(schema):
    """ Exports schema to Laravel migrations """
    try:
        global migrations

        indent = " " * 12
        ordered_tables = order_tables(schema)
        table_dict = {t.name: t for t in schema.tables}

        for table_name in ordered_tables:
            table = table_dict[table_name]
            print(f"Exporting table: {table_name}")
            
            # Control variables
            created_at = updated_at = deleted_at = False
            timestamps = timestamps_nullable = False
            created_at_nullable = updated_at_nullable = False

            morphs = []
            morphs_id = []
            morphs_type = []

            # Check timestamps and morphs
            for column in table.columns:
                # Check if the table has timestamps (created_at and updated_at) and if they allow null values
                if column.name == 'created_at':
                    created_at = True
                    if column.isNotNull != 1:
                        created_at_nullable = True
                elif column.name == 'updated_at':
                    updated_at = True
                    if column.isNotNull != 1:
                        updated_at_nullable = True
                elif column.name == 'deleted_at':
                    deleted_at = True
                # Check if the table has polymorphic relationships
                elif column.name.endswith('able_id'):
                    morphs_id.append(column.name.replace("_id", ""))
                elif column.name.endswith('able_type'):
                    morphs_type.append(column.name.replace("_type", ""))

            if created_at and updated_at:
                timestamps = True
                if created_at_nullable and updated_at_nullable:
                    timestamps_nullable = True

            for morph_name in morphs_id:
                if morph_name in morphs_type:
                    morphs.append(morph_name)

            # Check if the table has a primary key
            primary_key = [col for col in table.indices if col.isPrimary == 1]
            primary_key = primary_key[0] if len(primary_key) > 0 else None

            if hasattr(primary_key, 'columns'):
                primary_col = primary_key.columns[0].referencedColumn
            else:
                primary_col = None

            before_columns = []
            if table.tableEngine != 'InnoDB':
                before_columns.append(f"{indent}$table->engine = '{table.tableEngine}';")

            # Generating columns
            columns_sql = []
            for column in table.columns:
                column_name = column.name
                column_type = column.simpleType.name if column.simpleType else column.userType.name
                force_not_nullable = False

                if column == primary_col:
                    if column_type == "BIGINT":
                        column_type = "BIG_INCREMENTS"
                    elif column_type == "MEDIUMINT":
                        column_type = "MEDIUM_INCREMENTS"
                    elif column_type == "SMALLINT":
                        column_type = "SMALL_INCREMENTS"
                    elif column_type == "TINYINT":
                        column_type = "TINY_INCREMENTS"
                    elif column_type == "CHAR" and column.length == 36:
                        column_type = "UUID"
                    else:
                        column_type = "INCREMENTS"

                # Because MySQL Workbench doesnt works with boolean datatype
                if column_type == "TINYINT" and 'UNSIGNED' in column.flags and column.defaultValue in [0, 1]: 
                    column_type = "BOOLEAN"

                if column_type in ['BIGINT','INT','TINYINT','MEDIUMINT','SMALLINT'] and 'UNSIGNED' in column.flags:
                    column_type = "UNSIGNED_" + column_type

                if column_name == 'remember_token' and column_type == 'VARCHAR' and column.length == 100:
                    column_type = "REMEMBER_TOKEN"

                if (column_name == 'created_at' or column_name == 'updated_at') and (timestamps is True or timestamps_nullable is True):
                    continue

                if column_name == 'deleted_at':
                    continue

                if column_name.replace('_type', '') in morphs:
                    continue

                if column_name.replace('_id', '') in morphs:
                    force_not_nullable = True
                    column_name = column_name.replace('_id', '')
                    column_type = ("MORPHS" if column.isNotNull == 1 else "NULLABLE_MORPHS")

                # Check if the column is of type ENUM or SET and get the explicit parameters
                explicit_params = None
                if column_type in ['ENUM', 'SET']:
                    explicit_params = f"[{column.datatypeExplicitParams.strip('()')}]" 

                laravel_type = types_map.get(column_type.upper(), 'string')  # Default: string

                column_def = f"$table->{laravel_type}('{column_name}')" if explicit_params is None else f"$table->{laravel_type}('{column_name}', {explicit_params})"

                if column.isNotNull != 1 and force_not_nullable is False:
                    column_def += "->nullable()"

                # Check if the column is primary
                is_primary = any(index.indexType == "PRIMARY" and len(index.columns) == 1 and column in [col.referencedColumn for col in index.columns] for index in table.indices)
                if is_primary:
                    column_def += "->primary()"

                # Check if the column is unique
                is_unique = any(index.indexType == "UNIQUE" and len(index.columns) == 1 and column in [col.referencedColumn for col in index.columns] for index in table.indices)
                if is_unique:
                    column_def += "->unique()"
                
                if column.defaultValue:
                    if column_type in ['DATETIME', 'DATE', 'TIME', 'TIMESTAMP'] and column.defaultValue == "CURRENT_TIMESTAMP":
                        column_def += "->useCurrent()"
                    elif column_type == 'BOOLEAN':
                        column_def += f"->default({'TRUE' if column.defaultValue == 1 else 'FALSE'})"
                    else:
                        column_def += f"->default({column.defaultValue})"
                
                if column.comment:
                    column_def += f"->comment('{column.comment}')"

                columns_sql.append(indent + column_def + ";")

            # Add timestamps & softDeletes
            if timestamps:
                columns_sql.append(indent + f"$table->timestamps();")
            elif timestamps_nullable:
                columns_sql.append(indent + f"$table->nullableTimestamps();")
            
            if deleted_at:
                columns_sql.append(indent + f"$table->softDeletes();")

            # Generate indexes
            indexes_sql = []
            for index in table.indices:
                index_columns = ", ".join([f"'{col.referencedColumn.name}'" for col in index.columns])

                if index.indexType == "PRIMARY":
                    if (len(index.columns) > 1):
                        indexes_sql.append(indent + f"$table->primary([{index_columns}]);")
                elif index.indexType == "UNIQUE":
                    if (len(index.columns) > 1):
                        indexes_sql.append(indent + f"$table->unique([{index_columns}]);")
                else:
                    indexes_sql.append(indent + f"$table->index([{index_columns}]);")

            # Generate foreign keys
            foreign_keys_sql = []
            for fk in table.foreignKeys:
                fk_column = fk.columns[0].name
                ref_table = fk.referencedColumns[0].owner.name
                ref_column = fk.referencedColumns[0].name

                on_delete = fk.deleteRule.lower() if fk.deleteRule else "restrict"
                on_update = fk.updateRule.lower() if fk.updateRule else "restrict"

                foreign_keys_sql.append(
                    indent + 
                    f"$table->foreign('{fk_column}')"
                    f"->references('{ref_column}')->on('{ref_table}')"
                    f"->onDelete('{on_delete}')"
                    f"->onUpdate('{on_update}');"
                )

            nl = chr(10)

            # Creating the migration code
            migration_code = f"""<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration 
{{
    /**
     * Run the migrations.
     */
    public function up(): void
    {{
        Schema::create('{table_name}', function (Blueprint $table) {{
{''.join([
    nl.join(before_columns) + nl if before_columns else '',
    nl.join(columns_sql),
    nl + nl.join(indexes_sql) if indexes_sql else '',
    nl + nl.join(foreign_keys_sql) if foreign_keys_sql else ''
])}
        }});
    }}

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {{
        Schema::dropIfExists('{table_name}');
    }}
}};

"""
            migrations[schema.name][table_name] = migration_code
            migration_tables[schema.name].append(table_name)

    except Exception as e:
        error_message = f"Error exporting schema '{schema.name}': {str(e)}\n{traceback.format_exc()}"
        print(error_message)
        mforms.Utilities.show_error("Export Error", error_message, "OK", "", "")
        return {}

class LaravelMigrationWizard(WizardForm):
    """ UI to review and save migrations """
    def __init__(self, title, schema_sql_dict):
        super().__init__(None)
        self.set_name("laravel_migration_wizard")
        self.set_title(title)

        for schema_name, sql_text in schema_sql_dict.items():
            self.add_page(LaravelMigrationWizardSchemaPage(self, schema_name, sql_text))

class LaravelMigrationWizardSchemaPage(WizardPage):
    """ Wizard Page for displaying migrations """
    def __init__(self, owner, schema_name, sql_text):
        super().__init__(owner, f"Review migrations for '{schema_name}' schema:")

        self.schema_name = schema_name
        self.save_button = newButton()
        self.save_button.set_text("Save migrations...")
        self.save_button.set_tooltip("Select folder to save migration files")
        self.save_button.add_clicked_callback(self.save_clicked)

        self.sql_text = newCodeEditor()
        self.sql_text.set_language(mforms.LanguageMySQL)
        self.sql_text.set_text(sql_text)

        button_box = mforms.newBox(True)
        button_box.set_spacing(12)
        button_box.add(self.save_button, False, True)

        self.content.add_end(button_box, False, True)
        self.content.add_end(self.sql_text, True, True)

    def save_clicked(self):
        global migrations
        schema_name = self.schema_name

        print(f"Debug: Tentando salvar migrações para {schema_name}.")
        print(f"Debug: Chaves em migrations[{schema_name}]: {migrations[schema_name].keys()}")

        if schema_name not in migrations or not migrations[schema_name]:
            mforms.Utilities.show_message("Export Error", f"No migrations found for schema: {schema_name}", "OK", "", "")
            return

        file_chooser = mforms.newFileChooser(self.main, mforms.OpenDirectory)

        print(f"Debug: Salvando {schema_name}, migrations.keys() -> {migrations.keys()}")

        if file_chooser.run_modal() == mforms.ResultOk:
            path = file_chooser.get_path()
            now = datetime.datetime.now()

            i = len(glob.glob(path + "/*_table.php"))

            for table_name, migration_data in migrations[schema_name].items():
                try:
                    search_format = f"*_create_{table_name}_table.php"
                    search = glob.glob(path + "/" + search_format)

                    for file in search:
                        with open(file, 'w+') as f:
                            f.write(migration_data)

                    if len(search) == 0:
                        save_format = f"{now.strftime('%Y_%m_%d')}_{str(i).zfill(6)}_create_{table_name}_table.php"
                        with open(path + "/" + save_format, 'w+') as f:
                            f.write(migration_data)
                            i += 1

                except IOError as e:
                    mforms.Utilities.show_error(
                        'Save to File',
                        f'Could not save to file "{path}": {str(e)}',
                        'OK', '', ''
                    )

# Attempt to run the script via Workbench shell
if __name__ == "__main__":
    try:
        laravel_migration(grt.root.wb.doc.physicalModels[0].catalog)
    except Exception as e:
        error_message = f"Error running the plugin: {str(e)}\n{traceback.format_exc()}"
        print(error_message)
        mforms.Utilities.show_error("Critical Error", error_message, "OK", "", "")
