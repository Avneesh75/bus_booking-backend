@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  BusGo — Database Reset Script
REM  Run this once after the UUID7 model changes to wipe and recreate the DB.
REM  WARNING: This deletes ALL existing data.
REM ─────────────────────────────────────────────────────────────────────────────

echo.
echo [1/5] Deleting old database...
if exist db.sqlite3 del /f db.sqlite3
echo       Done.

echo.
echo [2/5] Removing old migration files (keeping __init__.py)...
for %%f in (booking\migrations\0*.py) do del /f "%%f"
echo       Done.

echo.
echo [3/5] Creating fresh migrations...
python manage.py makemigrations booking
if %errorlevel% neq 0 ( echo ERROR: makemigrations failed & pause & exit /b 1 )

echo.
echo [4/5] Applying migrations...
python manage.py migrate
if %errorlevel% neq 0 ( echo ERROR: migrate failed & pause & exit /b 1 )

echo.
echo [5/6] Seeding sample data (companies, buses, routes, trips, bookings)...
python manage.py seed_data
if %errorlevel% neq 0 ( echo ERROR: seed_data failed & pause & exit /b 1 )

echo.
echo [6/6] Done!
echo.
echo ─────────────────────────────────────────────────────────────────────────────
echo  Reset complete!
echo  Admin login  -^>  username: admin       password: Admin@123
echo  Staff login  -^>  redbus_staff / vrl_staff   password: Staff@123
echo  Customers    -^>  priya_sharma / rahul_verma / anita_singh   password: Test@1234
echo.
echo  Start the server:  python manage.py runserver
echo ─────────────────────────────────────────────────────────────────────────────
pause
