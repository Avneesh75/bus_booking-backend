"""
python manage.py seed_data         — seed (skips existing, safe to re-run)
python manage.py seed_data --reset  — wipe everything and start fresh
"""
import random
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from booking.models import (
    Company, UserProfile,
    Route, RouteStop,
    Bus, Seat,
    Driver,
    Trip, SeatAvailability,
    Booking, BookingSeat, PassengerDetail,
    Payment, BusLocation,
)


# ── Master data ───────────────────────────────────────────────────────────────

COMPANIES = [
    {"name": "RedBus Express",  "slug": "redbus-express"},
    {"name": "VRL Travels",     "slug": "vrl-travels"},
]

ROUTES = [
    {"source": "Delhi",     "destination": "Mumbai",    "distance_km": 1400, "company_idx": 0,
     "stops": [
         {"name": "Mathura",  "order": 1, "arrival_offset_mins":  90},
         {"name": "Agra",     "order": 2, "arrival_offset_mins": 150},
         {"name": "Gwalior",  "order": 3, "arrival_offset_mins": 270},
         {"name": "Bhopal",   "order": 4, "arrival_offset_mins": 480},
         {"name": "Indore",   "order": 5, "arrival_offset_mins": 660},
         {"name": "Surat",    "order": 6, "arrival_offset_mins": 900},
     ]},
    {"source": "Delhi",     "destination": "Jaipur",    "distance_km": 280,  "company_idx": 0,
     "stops": [
         {"name": "Gurgaon",  "order": 1, "arrival_offset_mins":  40},
         {"name": "Rewari",   "order": 2, "arrival_offset_mins":  80},
         {"name": "Alwar",    "order": 3, "arrival_offset_mins": 150},
     ]},
    {"source": "Mumbai",    "destination": "Pune",      "distance_km": 150,  "company_idx": 0,
     "stops": [
         {"name": "Khopoli",  "order": 1, "arrival_offset_mins":  60},
         {"name": "Lonavala", "order": 2, "arrival_offset_mins":  90},
     ]},
    {"source": "Bangalore", "destination": "Chennai",   "distance_km": 350,  "company_idx": 1,
     "stops": [
         {"name": "Hosur",    "order": 1, "arrival_offset_mins":  50},
         {"name": "Krishnagiri","order":2,"arrival_offset_mins": 120},
         {"name": "Vellore",  "order": 3, "arrival_offset_mins": 210},
     ]},
    {"source": "Hyderabad", "destination": "Bangalore", "distance_km": 570,  "company_idx": 1,
     "stops": [
         {"name": "Kurnool",  "order": 1, "arrival_offset_mins": 120},
         {"name": "Bellary",  "order": 2, "arrival_offset_mins": 240},
         {"name": "Tumkur",   "order": 3, "arrival_offset_mins": 480},
     ]},
]

BUSES = [
    {"bus_number": "DL-01-AA-1234", "name": "Rajdhani Express", "bus_type": "LUXURY",  "total_seats": 40, "is_ac": True,  "company_idx": 0},
    {"bus_number": "MH-02-BB-5678", "name": "Sahyadri Travels", "bus_type": "NORMAL",  "total_seats": 40, "is_ac": False, "company_idx": 0},
    {"bus_number": "KA-03-CC-9012", "name": "Karnataka Deluxe", "bus_type": "LUXURY",  "total_seats": 40, "is_ac": True,  "company_idx": 1},
    {"bus_number": "TN-04-DD-3456", "name": "Southern Star",    "bus_type": "MINI",    "total_seats": 20, "is_ac": True,  "company_idx": 1},
    {"bus_number": "UP-05-EE-7890", "name": "Volvo Sleeper",    "bus_type": "SLEEPER", "total_seats": 36, "is_ac": True,  "company_idx": 0},
]

DRIVERS = [
    {"name": "Ramesh Kumar",    "license_number": "DL-0120110012345", "phone": "9876543210", "experience_years": 12, "company_idx": 0},
    {"name": "Suresh Yadav",    "license_number": "MH-0220120023456", "phone": "9765432109", "experience_years":  8, "company_idx": 0},
    {"name": "Prakash Sharma",  "license_number": "KA-0320130034567", "phone": "9654321098", "experience_years": 15, "company_idx": 1},
    {"name": "Arjun Singh",     "license_number": "TN-0420140045678", "phone": "9543210987", "experience_years":  6, "company_idx": 1},
    {"name": "Mohan Das",       "license_number": "UP-0520150056789", "phone": "9432109876", "experience_years": 10, "company_idx": 0},
]

# (route_idx, bus_idx, driver_idx, dep_offset_hours, duration_hours, price)
TRIPS = [
    (0, 0, 0,   8, 24, 1299),
    (0, 1, 1,  20, 26,  899),
    (0, 4, 2,  32, 24, 1499),   # Volvo Sleeper — Delhi→Mumbai
    (1, 1, 3,   7,  5,  449),
    (1, 2, 4,  14,  5,  599),
    (1, 3, 0,  22,  5,  349),
    (2, 0, 1,   6,  3,  299),
    (2, 1, 2,  15,  3,  249),
    (3, 2, 3,   9,  7,  649),
    (3, 0, 4,  21,  7,  749),
    (4, 1, 0,  10,  9,  549),
    (4, 2, 1,  18,  9,  699),
    (4, 4, 2,  26,  9,  849),   # Volvo Sleeper — Hyderabad→Bangalore
]

CUSTOMER_USERS = [
    {"username": "priya_sharma",  "email": "priya@example.com",  "password": "Test@1234", "phone": "9811223344", "company_idx": None},
    {"username": "rahul_verma",   "email": "rahul@example.com",  "password": "Test@1234", "phone": "9922334455", "company_idx": None},
    {"username": "anita_singh",   "email": "anita@example.com",  "password": "Test@1234", "phone": "9033445566", "company_idx": None},
    # Staff users tied to companies
    {"username": "redbus_staff",  "email": "staff1@redbus.com",  "password": "Staff@123", "phone": "9144556677", "company_idx": 0},
    {"username": "vrl_staff",     "email": "staff2@vrl.com",     "password": "Staff@123", "phone": "9255667788", "company_idx": 1},
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_seats(bus, total, is_sleeper=False):
    seats = []
    if is_sleeper:
        per_deck = total // 2
        for deck in ('LOWER', 'UPPER'):
            for n in range(1, per_deck + 1):
                seats.append(Seat(
                    bus=bus,
                    seat_number=f"{'L' if deck == 'LOWER' else 'U'}{n}",
                    seat_type='SLEEPER',
                    deck=deck,
                ))
    else:
        rows = "ABCDEFGHIJ"
        per_row = 4
        num_rows = total // per_row
        for r in range(num_rows):
            row_letter = rows[r] if r < len(rows) else str(r + 1)
            for col in range(1, per_row + 1):
                seat_type = "WINDOW" if col in (1, 4) else "AISLE"
                seats.append(Seat(bus=bus, seat_number=f"{row_letter}{col}", seat_type=seat_type, deck='LOWER'))
        if total % per_row:
            remaining = total % per_row
            r = num_rows
            row_letter = rows[r] if r < len(rows) else str(r + 1)
            for col in range(1, remaining + 1):
                seat_type = "WINDOW" if col in (1, remaining) else "AISLE"
                seats.append(Seat(bus=bus, seat_number=f"{row_letter}{col}", seat_type=seat_type, deck='LOWER'))
    return seats


FIRST_NAMES = ["Aarav", "Priya", "Rohan", "Sneha", "Vikram", "Ananya", "Arjun", "Kavya",
               "Raj", "Meera", "Kunal", "Divya", "Siddharth", "Pooja", "Aditya"]
LAST_NAMES  = ["Sharma", "Patel", "Singh", "Verma", "Kumar", "Gupta", "Joshi", "Rao",
               "Nair", "Menon", "Shah", "Iyer", "Reddy", "Mehta", "Das"]

def rand_name():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"

def rand_gender():
    return random.choice(['M', 'F', 'O'])

def rand_age():
    return random.randint(18, 65)


# ── Command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Seed the database with sample data for all models"

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help='Wipe Trips, Bookings, Payments and re-seed from scratch')

    def log(self, msg):
        self.stdout.write(f"  {msg}")

    def ok(self, msg):
        self.stdout.write(self.style.SUCCESS(f"  + {msg}"))

    def handle(self, *args, **options):
        self.stdout.write("\n--- BusGo Data Seeder ---\n")

        if options['reset']:
            counts = {
                'payments':  Payment.objects.count(),
                'bookings':  Booking.objects.count(),
                'trips':     Trip.objects.count(),
                'stops':     RouteStop.objects.count(),
                'locations': BusLocation.objects.count(),
            }
            Payment.objects.all().delete()
            Booking.objects.all().delete()
            Trip.objects.all().delete()
            RouteStop.objects.all().delete()
            BusLocation.objects.all().delete()
            self.stdout.write(self.style.WARNING(
                f"  Reset: deleted {counts['payments']} payments, "
                f"{counts['bookings']} bookings, {counts['trips']} trips, "
                f"{counts['stops']} stops, {counts['locations']} locations."
            ))

        # ── 1. Companies ──────────────────────────────────────────────────────
        self.stdout.write("\n[1] Companies")
        company_objs = []
        for c in COMPANIES:
            obj, created = Company.objects.get_or_create(
                slug=c["slug"],
                defaults={"name": c["name"], "is_active": True}
            )
            company_objs.append(obj)
            if created:
                self.ok(f"Company: {obj.name}")
            else:
                self.log(f"Company exists: {obj.name}")

        # ── 2. Users ──────────────────────────────────────────────────────────
        self.stdout.write("\n[2] Users")
        admin, created = User.objects.get_or_create(
            username='admin',
            defaults={'email': 'admin@busgo.com', 'is_staff': True, 'is_superuser': True}
        )
        if created:
            admin.set_password('Admin@123')
            admin.save()
            self.ok("Admin  username=admin  password=Admin@123")
        else:
            if not admin.is_staff or not admin.is_superuser:
                admin.is_staff = True; admin.is_superuser = True; admin.save()
            self.log("Admin user already exists")

        customer_objs = []
        for u in CUSTOMER_USERS:
            user, created = User.objects.get_or_create(
                username=u["username"],
                defaults={
                    'email': u["email"],
                    'password': make_password(u["password"]),
                    'is_staff': u["company_idx"] is not None,
                }
            )
            customer_objs.append(user)
            if created:
                # UserProfile is auto-created by signal, just set extra fields
                profile = user.profile
                profile.phone   = u["phone"]
                profile.company = company_objs[u["company_idx"]] if u["company_idx"] is not None else None
                profile.save()
                self.ok(f"User: {user.username}  ({'staff @ ' + company_objs[u['company_idx']].name if u['company_idx'] is not None else 'customer'})")
            else:
                self.log(f"User exists: {user.username}")

        # ── 3. Routes ─────────────────────────────────────────────────────────
        self.stdout.write("\n[3] Routes & Stops")
        route_objs = []
        for r in ROUTES:
            obj, created = Route.objects.get_or_create(
                source=r["source"], destination=r["destination"],
                defaults={
                    "distance_km": r["distance_km"],
                    "company": company_objs[r["company_idx"]],
                }
            )
            route_objs.append(obj)
            route_label = f"{obj.source} -> {obj.destination}"
            if created:
                self.ok(f"Route: {route_label}")
            else:
                self.log(f"Route exists: {route_label}")

            # Stops
            for s in r.get("stops", []):
                stop, s_created = RouteStop.objects.get_or_create(
                    route=obj, order=s["order"],
                    defaults={
                        "name":                s["name"],
                        "arrival_offset_mins": s["arrival_offset_mins"],
                    }
                )
                if s_created:
                    self.log(f"    Stop #{s['order']}: {stop.name}  (+{s['arrival_offset_mins']} min)")

        # ── 4. Buses + Seats ──────────────────────────────────────────────────
        self.stdout.write("\n[4] Buses & Seats")
        bus_objs = []
        for b in BUSES:
            is_sleeper = b["bus_type"] == "SLEEPER"
            bus, created = Bus.objects.get_or_create(
                bus_number=b["bus_number"],
                defaults={
                    "name": b["name"], "bus_type": b["bus_type"],
                    "total_seats": b["total_seats"], "is_ac": b["is_ac"],
                    "company": company_objs[b["company_idx"]],
                }
            )
            bus_objs.append(bus)
            if created:
                seats = make_seats(bus, b["total_seats"], is_sleeper=is_sleeper)
                Seat.objects.bulk_create(seats)
                self.ok(f"Bus: {bus}  ({len(seats)} seats created)")
            else:
                self.log(f"Bus exists: {bus}")

        # ── 5. Drivers ────────────────────────────────────────────────────────
        self.stdout.write("\n[5] Drivers")
        driver_objs = []
        for d in DRIVERS:
            driver, created = Driver.objects.get_or_create(
                license_number=d["license_number"],
                defaults={
                    "name": d["name"], "phone": d["phone"],
                    "experience_years": d["experience_years"], "is_active": True,
                    "company": company_objs[d["company_idx"]],
                }
            )
            driver_objs.append(driver)
            if created:
                self.ok(f"Driver: {driver.name}  ({d['experience_years']} yrs)")
            else:
                self.log(f"Driver exists: {driver.name}")

        # ── 6. Trips (signal auto-creates SeatAvailability) ───────────────────
        self.stdout.write("\n[6] Trips")
        now       = timezone.now().replace(minute=0, second=0, microsecond=0)
        trip_objs = []
        for route_i, bus_i, driver_i, dep_offset, duration, price in TRIPS:
            dep = now + timedelta(hours=dep_offset)
            arr = dep + timedelta(hours=duration)
            trip, created = Trip.objects.get_or_create(
                bus=bus_objs[bus_i], route=route_objs[route_i], departure_time=dep,
                defaults={
                    "arrival_time": arr, "price": price,
                    "is_active": True, "driver": driver_objs[driver_i],
                }
            )
            trip_objs.append(trip)
            if created:
                sa_count = SeatAvailability.objects.filter(trip=trip).count()
                route_label = f"{trip.route.source} -> {trip.route.destination}"
                self.ok(f"Trip: {trip.bus.name}  {route_label}  ({sa_count} seats)")

        # ── 7. BusLocation for every trip ────────────────────────────────────
        self.stdout.write("\n[7] Bus Locations")
        BASE_LOCATIONS = [
            (28.6139, 77.2090),   # Delhi
            (19.0760, 72.8777),   # Mumbai
            (18.5204, 73.8567),   # Pune
            (12.9716, 77.5946),   # Bangalore
            (17.3850, 78.4867),   # Hyderabad
            (23.0225, 72.5714),   # Ahmedabad
            (26.9124, 75.7873),   # Jaipur
            (13.0827, 80.2707),   # Chennai
        ]
        for trip in trip_objs:
            lat, lon = random.choice(BASE_LOCATIONS)
            lat += round(random.uniform(-0.5, 0.5), 4)
            lon += round(random.uniform(-0.5, 0.5), 4)
            loc, created = BusLocation.objects.get_or_create(
                trip=trip,
                defaults={
                    "latitude":   lat,
                    "longitude":  lon,
                    "speed_kmph": round(random.uniform(40, 85), 1),
                }
            )
            if created:
                self.log(f"Location set for trip {trip.id}: ({lat}, {lon})")

        # ── 8. Sample Bookings, BookingSeats, PassengerDetails, Payments ──────
        self.stdout.write("\n[8] Bookings, Passengers & Payments")
        customers = [u for u in customer_objs if not u.is_staff]  # only regular customers book

        SAMPLE_BOOKINGS = [
            # (trip_idx, user_idx_in_customers, num_seats, status, pay_status)
            (0,  0, 2, 'BOOKED',    'SUCCESS'),
            (1,  1, 1, 'BOOKED',    'SUCCESS'),
            (2,  2, 2, 'PENDING',   'PENDING'),
            (3,  0, 3, 'BOOKED',    'SUCCESS'),
            (4,  1, 1, 'CANCELLED', 'FAILED'),
            (5,  2, 2, 'BOOKED',    'SUCCESS'),
            (6,  0, 1, 'BOOKED',    'SUCCESS'),
            (7,  1, 2, 'PENDING',   'PENDING'),
            (8,  2, 1, 'BOOKED',    'SUCCESS'),
            (9,  0, 2, 'BOOKED',    'SUCCESS'),
            (10, 1, 1, 'CANCELLED', 'FAILED'),
            (11, 2, 2, 'BOOKED',    'SUCCESS'),
        ]

        bookings_created = 0
        for trip_i, cust_i, num_seats, b_status, p_status in SAMPLE_BOOKINGS:
            if trip_i >= len(trip_objs) or cust_i >= len(customers):
                continue
            trip = trip_objs[trip_i]
            user = customers[cust_i % len(customers)]

            # Pick available (not yet booked) seats for this trip
            avail = list(
                SeatAvailability.objects
                .filter(trip=trip, is_booked=False)
                .select_related('seat')[:num_seats]
            )
            if len(avail) < num_seats:
                self.log(f"  Not enough free seats on trip {trip_i}, skipping booking")
                continue

            # Skip if this user already has a booking on this trip
            if Booking.objects.filter(user=user, trip=trip).exists():
                continue

            price        = trip.price
            total_amount = price * len(avail)

            # Pick random route stops for boarding/alighting (sometimes None)
            route_stops = list(RouteStop.objects.filter(route=trip.route).order_by('order'))
            from_stop = None
            to_stop   = None
            if route_stops and random.random() > 0.5:
                idx = random.randint(0, len(route_stops) - 1)
                from_stop = route_stops[idx]
                later = [s for s in route_stops if s.order > from_stop.order]
                if later:
                    to_stop = random.choice(later)

            booking = Booking.objects.create(
                user=user, trip=trip,
                status=b_status, total_amount=total_amount,
                from_stop=from_stop, to_stop=to_stop,
                created_by=user,
            )

            # Mark seats as booked
            for sa in avail:
                sa.is_booked = True
                sa.save(update_fields=['is_booked'])

                bs = BookingSeat.objects.create(booking=booking, seat=sa.seat)

                # Passenger detail for each seat
                PassengerDetail.objects.create(
                    booking_seat=bs,
                    name=rand_name(),
                    age=rand_age(),
                    gender=rand_gender(),
                )

            # Payment record
            if not Payment.objects.filter(booking=booking).exists():
                Payment.objects.create(
                    booking=booking,
                    razorpay_order_id=f"order_{''.join(random.choices('abcdefghijklmnopqrstuvwxyz0123456789', k=14))}",
                    transaction_id=f"pay_{''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=16))}",
                    amount=total_amount,
                    status=p_status,
                    payment_method=random.choice(['RAZORPAY', 'UPI', 'CARD', 'NETBANKING']),
                    created_by=user,
                )

            bookings_created += 1
            stop_info = f" ({from_stop.name} -> {to_stop.name})" if from_stop and to_stop else ""
            self.ok(
                f"Booking: {user.username} × {trip.bus.name}"
                f" [{len(avail)} seats]{stop_info}  status={b_status}"
            )

        # ── Summary ───────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS(
            "\n-------------------------------------\n"
            "  Seeding complete!\n"
            f"  Companies : {Company.objects.count()}\n"
            f"  Users     : {User.objects.count()}\n"
            f"  Routes    : {Route.objects.count()} with {RouteStop.objects.count()} stops\n"
            f"  Buses     : {Bus.objects.count()} with {Seat.objects.count()} seats\n"
            f"  Drivers   : {Driver.objects.count()}\n"
            f"  Trips     : {Trip.objects.count()}\n"
            f"  Bookings  : {Booking.objects.count()}\n"
            f"  Payments  : {Payment.objects.count()}\n"
            f"  Locations : {BusLocation.objects.count()}\n"
            "-------------------------------------\n"
            "  Admin login  -> admin / Admin@123\n"
            "  Staff login  -> redbus_staff / Staff@123\n"
            "  Customers    -> priya_sharma / Test@1234\n"
            "-------------------------------------\n"
        ))
