from django.db import models
from django.contrib.auth.models import User
from .utils import uuid7


# ── Abstract Base (UUID7 PK on every subclass) ────────────────────────────────
class TimeMixin(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="created_%(class)s"
    )
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="updated_%(class)s"
    )

    class Meta:
        abstract = True


# ── Company (multi-tenant) ────────────────────────────────────────────────────
class Company(models.Model):
    id        = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    name      = models.CharField(max_length=200, unique=True)
    slug      = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Contact info (shown to customers on booking page)
    phone     = models.CharField(max_length=20, blank=True, null=True)
    email     = models.EmailField(blank=True, null=True)
    address   = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Companies'

    def __str__(self):
        return self.name


# ── User Profile ──────────────────────────────────────────────────────────────
class UserProfile(models.Model):
    id      = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user    = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone   = models.CharField(max_length=15, blank=True, null=True)
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='staff_profiles'
    )

    def __str__(self):
        return f"Profile: {self.user.username}"


# ── Driver ────────────────────────────────────────────────────────────────────
class Driver(TimeMixin):
    name             = models.CharField(max_length=100)
    license_number   = models.CharField(max_length=50, unique=True)
    phone            = models.CharField(max_length=15)
    experience_years = models.IntegerField(default=0)
    is_active        = models.BooleanField(default=True)
    company          = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='drivers'
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.license_number})"


# ── Route ─────────────────────────────────────────────────────────────────────
class Route(TimeMixin):
    source      = models.CharField(max_length=100)
    destination = models.CharField(max_length=100)
    distance_km = models.FloatField(null=True, blank=True)
    company     = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='routes'
    )

    class Meta:
        ordering = ['source']

    def __str__(self):
        return f"{self.source} -> {self.destination}"


# ── Route Stop (intermediate stops on a route) ────────────────────────────────
class RouteStop(models.Model):
    id                  = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    route               = models.ForeignKey(Route, on_delete=models.CASCADE, related_name='stops')
    name                = models.CharField(max_length=100)
    order               = models.PositiveIntegerField()          # 0 = source terminal
    arrival_offset_mins = models.IntegerField(default=0)         # minutes from departure

    class Meta:
        ordering = ['order']
        unique_together = ['route', 'order']

    def __str__(self):
        return f"{self.name} (Route: {self.route}, pos: {self.order})"


# ── Bus ───────────────────────────────────────────────────────────────────────
class Bus(TimeMixin):
    BUS_TYPE = (
        ('MINI',    'Mini Bus'),
        ('NORMAL',  'Normal'),
        ('LUXURY',  'Luxury'),
        ('SLEEPER', 'Sleeper'),
    )

    bus_number  = models.CharField(max_length=20, unique=True)
    name        = models.CharField(max_length=100)
    bus_type    = models.CharField(max_length=20, choices=BUS_TYPE)
    total_seats = models.IntegerField()
    is_ac       = models.BooleanField(default=False)
    is_active   = models.BooleanField(default=True)
    amenities   = models.JSONField(default=list, blank=True)   # e.g. ["WiFi","USB Charging"]
    company     = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='buses'
    )

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Buses'

    def __str__(self):
        return f"{self.name} ({self.bus_number})"


# ── Seat ──────────────────────────────────────────────────────────────────────
class Seat(TimeMixin):
    SEAT_TYPE = (
        ('WINDOW',  'Window'),
        ('AISLE',   'Aisle'),
        ('SLEEPER', 'Sleeper'),
    )

    bus         = models.ForeignKey(Bus, on_delete=models.CASCADE, related_name='seats')
    seat_number = models.CharField(max_length=10)
    seat_type   = models.CharField(max_length=20, choices=SEAT_TYPE)
    deck        = models.CharField(
        max_length=10, default='LOWER',
        choices=[('LOWER', 'Lower'), ('UPPER', 'Upper')]
    )

    class Meta:
        unique_together = ['bus', 'seat_number']
        ordering = ['seat_number']

    def __str__(self):
        return f"{self.bus.bus_number} - {self.seat_number}"


# ── Trip ──────────────────────────────────────────────────────────────────────
class Trip(TimeMixin):
    bus            = models.ForeignKey(Bus,    on_delete=models.CASCADE,  related_name='trips')
    route          = models.ForeignKey(Route,  on_delete=models.CASCADE,  related_name='trips')
    driver         = models.ForeignKey(Driver, on_delete=models.SET_NULL, null=True, blank=True, related_name='trips')
    departure_time = models.DateTimeField()
    arrival_time   = models.DateTimeField()
    price          = models.DecimalField(max_digits=10, decimal_places=2)
    is_active      = models.BooleanField(default=True)
    # Age-based fare tiers (applied at booking time)
    child_max_age    = models.PositiveIntegerField(default=12, help_text="Ages < 5 travel free; 5 to this age pays child_fare_pct")
    senior_min_age   = models.PositiveIntegerField(default=60, help_text="Ages >= this pay senior_fare_pct")
    child_fare_pct   = models.DecimalField(max_digits=5, decimal_places=2, default=50,  help_text="% of base fare for child tickets")
    senior_fare_pct  = models.DecimalField(max_digits=5, decimal_places=2, default=80,  help_text="% of base fare for senior tickets")
    cancellation_charge_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Cancellation fee as % of total amount (0 = free cancellation)"
    )

    class Meta:
        ordering = ['departure_time']

    def __str__(self):
        return f"{self.bus} | {self.route} | {self.departure_time}"


# ── Seat Availability ─────────────────────────────────────────────────────────
class SeatAvailability(models.Model):
    id        = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    trip      = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='seat_availabilities')
    seat      = models.ForeignKey(Seat, on_delete=models.CASCADE, related_name='availabilities')
    is_booked = models.BooleanField(default=False)

    class Meta:
        unique_together = ['trip', 'seat']
        verbose_name_plural = 'Seat Availabilities'

    def __str__(self):
        return f"{self.seat} on Trip {self.trip_id} — {'Booked' if self.is_booked else 'Available'}"


# ── Booking ───────────────────────────────────────────────────────────────────
class Booking(TimeMixin):
    STATUS = (
        ('BOOKED',    'Booked'),
        ('CANCELLED', 'Cancelled'),
        ('PENDING',   'Pending'),
    )

    user         = models.ForeignKey(User,      on_delete=models.CASCADE,  related_name='bookings')
    trip         = models.ForeignKey(Trip,      on_delete=models.CASCADE,  related_name='bookings')
    status       = models.CharField(max_length=20, choices=STATUS, default='PENDING')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    # Intermediate stop support
    from_stop    = models.ForeignKey(
        RouteStop, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='departing_bookings'
    )
    to_stop      = models.ForeignKey(
        RouteStop, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='arriving_bookings'
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Booking {str(self.id)[:8]}… — {self.user.username} ({self.status})"


# ── Booking Seat ──────────────────────────────────────────────────────────────
class BookingSeat(models.Model):
    id      = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='booking_seats')
    seat    = models.ForeignKey(Seat,    on_delete=models.CASCADE, related_name='booking_seats')

    class Meta:
        unique_together = ['booking', 'seat']

    def __str__(self):
        return f"Booking {self.booking_id} — Seat {self.seat}"


# ── Passenger Detail (per booked seat) ───────────────────────────────────────
class PassengerDetail(models.Model):
    GENDER = (('M', 'Male'), ('F', 'Female'), ('O', 'Other'))

    id           = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    booking_seat = models.OneToOneField(BookingSeat, on_delete=models.CASCADE, related_name='passenger')
    name         = models.CharField(max_length=100)
    age          = models.PositiveIntegerField()
    gender       = models.CharField(max_length=1, choices=GENDER)
    fare         = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.name} ({self.age}, {self.get_gender_display()})"


# ── Payment ───────────────────────────────────────────────────────────────────
class Payment(TimeMixin):
    PAYMENT_STATUS = (('SUCCESS', 'Success'), ('FAILED', 'Failed'), ('PENDING', 'Pending'))
    PAYMENT_METHOD = (
        ('RAZORPAY', 'Razorpay'), ('UPI', 'UPI'),
        ('CARD', 'Card'), ('NETBANKING', 'Net Banking'),
    )

    booking           = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='payment')
    razorpay_order_id = models.CharField(max_length=100, blank=True, null=True)
    transaction_id    = models.CharField(max_length=100, blank=True, null=True)
    amount            = models.DecimalField(max_digits=10, decimal_places=2)
    status            = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='PENDING')
    payment_method    = models.CharField(max_length=20, choices=PAYMENT_METHOD, default='RAZORPAY')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.transaction_id or 'N/A'} — {self.status}"


# ── Live Bus Location ─────────────────────────────────────────────────────────
class BusLocation(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    trip       = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name='location')
    latitude   = models.FloatField(default=28.6139)
    longitude  = models.FloatField(default=77.2090)
    speed_kmph = models.FloatField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Trip {self.trip_id} @ {self.latitude},{self.longitude}"


# ── Signals ───────────────────────────────────────────────────────────────────
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=Trip)
def create_seat_availability(sender, instance, created, **kwargs):
    """Auto-create SeatAvailability rows when a Trip is created."""
    if created:
        seats = Seat.objects.filter(bus=instance.bus)
        SeatAvailability.objects.bulk_create(
            [SeatAvailability(trip=instance, seat=seat, is_booked=False) for seat in seats],
            ignore_conflicts=True,
        )


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Auto-create UserProfile on user creation."""
    if created:
        UserProfile.objects.get_or_create(user=instance)
