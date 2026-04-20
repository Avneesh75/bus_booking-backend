from rest_framework import serializers
from django.contrib.auth.models import User
from .models import (
    Company, UserProfile, Route, RouteStop,
    Bus, Seat, Trip, Driver,
    SeatAvailability, Booking, BookingSeat, PassengerDetail,
    Payment, BusLocation,
)


# ─────────────────────────────────────────────────────────────────────────────
# Company
# ─────────────────────────────────────────────────────────────────────────────
class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model  = Company
        fields = ['id', 'name', 'slug', 'is_active', 'phone', 'email', 'address']


# ─────────────────────────────────────────────────────────────────────────────
# User / Profile
# ─────────────────────────────────────────────────────────────────────────────
class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model  = UserProfile
        fields = ['phone']


class UserSerializer(serializers.ModelSerializer):
    phone   = serializers.SerializerMethodField()
    company = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = ['id', 'username', 'email', 'is_staff', 'is_superuser', 'is_active', 'phone', 'company']

    def get_phone(self, obj):
        try:
            return obj.profile.phone or ''
        except UserProfile.DoesNotExist:
            return ''

    def get_company(self, obj):
        try:
            c = obj.profile.company
            return {'id': str(c.id), 'name': c.name, 'slug': c.slug} if c else None
        except UserProfile.DoesNotExist:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Route + Stops
# ─────────────────────────────────────────────────────────────────────────────
class RouteStopSerializer(serializers.ModelSerializer):
    class Meta:
        model  = RouteStop
        fields = ['id', 'name', 'order', 'arrival_offset_mins']


class RouteSerializer(serializers.ModelSerializer):
    stops_count = serializers.SerializerMethodField()

    class Meta:
        model  = Route
        fields = ['id', 'source', 'destination', 'distance_km', 'stops_count']

    def get_stops_count(self, obj):
        return obj.stops.count()


class RouteWithStopsSerializer(serializers.ModelSerializer):
    stops = RouteStopSerializer(many=True, read_only=True)

    class Meta:
        model  = Route
        fields = ['id', 'source', 'destination', 'distance_km', 'stops']


# ─────────────────────────────────────────────────────────────────────────────
# Bus / Driver / Seat
# ─────────────────────────────────────────────────────────────────────────────
class BusSerializer(serializers.ModelSerializer):
    seat_count = serializers.SerializerMethodField()
    company    = CompanySerializer(read_only=True)

    class Meta:
        model  = Bus
        fields = ['id', 'bus_number', 'name', 'bus_type', 'total_seats',
                  'is_ac', 'is_active', 'amenities', 'seat_count', 'company']

    def get_seat_count(self, obj):
        return obj.seats.count()


class DriverSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Driver
        fields = ['id', 'name', 'license_number', 'phone', 'experience_years', 'is_active']


class SeatSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Seat
        fields = ['id', 'seat_number', 'seat_type', 'deck']


# ─────────────────────────────────────────────────────────────────────────────
# Trip
# ─────────────────────────────────────────────────────────────────────────────
class TripSerializer(serializers.ModelSerializer):
    bus      = BusSerializer(read_only=True)
    route    = RouteSerializer(read_only=True)
    driver   = DriverSerializer(read_only=True)
    bus_id   = serializers.PrimaryKeyRelatedField(
        queryset=Bus.objects.all(),    source='bus',    write_only=True)
    route_id = serializers.PrimaryKeyRelatedField(
        queryset=Route.objects.all(),  source='route',  write_only=True)
    driver_id = serializers.PrimaryKeyRelatedField(
        queryset=Driver.objects.all(), source='driver', write_only=True,
        required=False, allow_null=True)

    class Meta:
        model  = Trip
        fields = ['id', 'bus', 'bus_id', 'route', 'route_id',
                  'driver', 'driver_id', 'departure_time', 'arrival_time',
                  'price', 'is_active', 'cancellation_charge_pct',
                  'child_max_age', 'senior_min_age', 'child_fare_pct', 'senior_fare_pct']


# ─────────────────────────────────────────────────────────────────────────────
# Seat Availability
# ─────────────────────────────────────────────────────────────────────────────
class SeatAvailabilitySerializer(serializers.ModelSerializer):
    seat = SeatSerializer(read_only=True)

    class Meta:
        model  = SeatAvailability
        fields = ['id', 'seat', 'is_booked']


# ─────────────────────────────────────────────────────────────────────────────
# Passenger Detail
# ─────────────────────────────────────────────────────────────────────────────
class PassengerDetailSerializer(serializers.ModelSerializer):
    seat_number = serializers.SerializerMethodField()
    fare_tier   = serializers.SerializerMethodField()

    class Meta:
        model  = PassengerDetail
        fields = ['id', 'name', 'age', 'gender', 'fare', 'fare_tier', 'seat_number']

    def get_seat_number(self, obj):
        return obj.booking_seat.seat.seat_number

    def get_fare_tier(self, obj):
        trip = obj.booking_seat.booking.trip
        if obj.age < 5:
            return 'infant'
        if obj.age < trip.child_max_age:
            return 'child'
        if obj.age >= trip.senior_min_age:
            return 'senior'
        return 'adult'


class PassengerInputSerializer(serializers.Serializer):
    """One passenger entry sent during booking creation."""
    seat_id = serializers.UUIDField()
    name    = serializers.CharField(max_length=100)
    age     = serializers.IntegerField(min_value=1, max_value=120)
    gender  = serializers.ChoiceField(choices=['M', 'F', 'O'])


# ─────────────────────────────────────────────────────────────────────────────
# Booking Seat
# ─────────────────────────────────────────────────────────────────────────────
class BookingSeatSerializer(serializers.ModelSerializer):
    seat      = SeatSerializer(read_only=True)
    passenger = PassengerDetailSerializer(read_only=True)

    class Meta:
        model  = BookingSeat
        fields = ['id', 'seat', 'passenger']


# ─────────────────────────────────────────────────────────────────────────────
# Booking
# ─────────────────────────────────────────────────────────────────────────────
class BookingSerializer(serializers.ModelSerializer):
    user          = UserSerializer(read_only=True)
    trip          = TripSerializer(read_only=True)
    booking_seats = BookingSeatSerializer(many=True, read_only=True)
    from_stop     = RouteStopSerializer(read_only=True)
    to_stop       = RouteStopSerializer(read_only=True)
    cancellation_charge = serializers.SerializerMethodField()
    refund_amount       = serializers.SerializerMethodField()

    class Meta:
        model  = Booking
        fields = ['id', 'user', 'trip', 'status', 'total_amount',
                  'from_stop', 'to_stop', 'booking_seats', 'created_at',
                  'cancellation_charge', 'refund_amount']

    def get_cancellation_charge(self, obj):
        pct = obj.trip.cancellation_charge_pct if obj.trip else 0
        return str(round(obj.total_amount * pct / 100, 2))

    def get_refund_amount(self, obj):
        pct = obj.trip.cancellation_charge_pct if obj.trip else 0
        charge = obj.total_amount * pct / 100
        return str(round(obj.total_amount - charge, 2))


class BookingCreateSerializer(serializers.Serializer):
    trip_id      = serializers.UUIDField()
    seat_ids     = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    from_stop_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    to_stop_id   = serializers.UUIDField(required=False, allow_null=True, default=None)
    passengers   = PassengerInputSerializer(many=True, required=False, default=[])

    def validate(self, data):
        try:
            trip = Trip.objects.get(id=data['trip_id'], is_active=True)
        except Trip.DoesNotExist:
            raise serializers.ValidationError({"trip_id": "Trip not found or inactive."})

        valid_ids = set(
            SeatAvailability.objects.filter(trip=trip).values_list('seat_id', flat=True)
        )
        invalid = set(data['seat_ids']) - valid_ids
        if invalid:
            raise serializers.ValidationError({"seat_ids": f"Seats not on this trip."})

        booked = list(
            SeatAvailability.objects
            .filter(trip=trip, seat_id__in=data['seat_ids'], is_booked=True)
            .values_list('seat_id', flat=True)
        )
        if booked:
            raise serializers.ValidationError({"seat_ids": "Some seats are already booked."})

        # Validate passengers: one per seat, seat_id must be in seat_ids
        seat_id_set = set(str(s) for s in data['seat_ids'])
        passenger_seat_ids = set(str(p['seat_id']) for p in data.get('passengers', []))
        if data.get('passengers') and not passenger_seat_ids.issubset(seat_id_set):
            raise serializers.ValidationError(
                {"passengers": "Passenger seat_ids must match selected seats."}
            )

        # Validate stops belong to the trip's route
        from_stop = None
        to_stop   = None
        if data.get('from_stop_id'):
            try:
                from_stop = RouteStop.objects.get(id=data['from_stop_id'], route=trip.route)
            except RouteStop.DoesNotExist:
                raise serializers.ValidationError({"from_stop_id": "Stop not found on this route."})
        if data.get('to_stop_id'):
            try:
                to_stop = RouteStop.objects.get(id=data['to_stop_id'], route=trip.route)
            except RouteStop.DoesNotExist:
                raise serializers.ValidationError({"to_stop_id": "Stop not found on this route."})
        if from_stop and to_stop and from_stop.order >= to_stop.order:
            raise serializers.ValidationError(
                {"to_stop_id": "Alighting stop must be after boarding stop."}
            )

        data['trip']      = trip
        data['from_stop'] = from_stop
        data['to_stop']   = to_stop
        return data


# ─────────────────────────────────────────────────────────────────────────────
# Payment
# ─────────────────────────────────────────────────────────────────────────────
class PaymentSerializer(serializers.ModelSerializer):
    booking = BookingSerializer(read_only=True)

    class Meta:
        model  = Payment
        fields = ['id', 'booking', 'razorpay_order_id', 'transaction_id',
                  'amount', 'status', 'payment_method', 'created_at']


class PaymentCreateSerializer(serializers.Serializer):
    booking_id = serializers.UUIDField()

    def validate(self, data):
        try:
            booking = Booking.objects.get(id=data['booking_id'])
        except Booking.DoesNotExist:
            raise serializers.ValidationError({"booking_id": "Booking not found."})
        if booking.status == 'CANCELLED':
            raise serializers.ValidationError({"booking_id": "Cannot pay for a cancelled booking."})
        if hasattr(booking, 'payment') and booking.payment.status == 'SUCCESS':
            raise serializers.ValidationError({"booking_id": "Already paid."})
        data['booking'] = booking
        return data


# ─────────────────────────────────────────────────────────────────────────────
# Bus Location
# ─────────────────────────────────────────────────────────────────────────────
class BusLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model  = BusLocation
        fields = ['trip_id', 'latitude', 'longitude', 'speed_kmph', 'updated_at']
