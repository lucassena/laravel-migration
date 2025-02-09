# MySQL Workbench Plugin: Laravel Migrations

This plugin exports a MySQL Workbench model to Laravel migrations. It generates migration files for Laravel projects based on the schema defined in MySQL Workbench. The plugin supports various MySQL data types and converts them to their corresponding Laravel migration types.

## Features

- Converts MySQL schema to Laravel migration files.
- Supports multiple schemas.
- Supports various MySQL data types and maps them to Laravel types.
- Handles foreign keys, indexes, timestamps, and polymorphic relationships.
- Generates migration files with proper naming conventions.
- Provides a wizard interface for reviewing and saving generated migrations.
- Topological sorting of tables to handle foreign key dependencies.

## Usage

1. Open MySQL Workbench and create a database model.
2. Add tables, columns, indexes, and foreign keys to the model.
3. Go to "Tools" -> "Catalog" -> "Export Laravel Migration".
4. Review the generated Laravel migration files for the schema.
5. Save the migration files to the desired location.
6. Click next if you have more than one schema and repeat the last two steps.
7. Copy the migration files to the Laravel project's "database/migrations" folder.
8. Run `php artisan migrate` to apply the migrations to the database.

## Requirements

- MySQL Workbench 8.0 or higher
- MySQL database model
- Laravel 8.x or higher
- PHP 7.3 or higher

## Author

Lucas Martins

## Version

0.9

## Release Date

2025-02-08

## License

MIT
