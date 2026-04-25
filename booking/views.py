from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.conf import settings
from datetime import date

import razorpay

from .models import (
    Company, Route, RouteStop, Bus, Trip, Seat,
    SeatAvailability, Booking, BookingSeat, PassengerDetail,
    Payment, Driver, BusLocation, UserProfile,
)
from .serializers import (
    CompanySerializer, UserSerializer,
    RouteSerializer, RouteStopSerializer,
    BusSerializer, TripSerializer, SeatAvailabilitySerializer,
    BookingSerializer, BookingCreateSerializer,
    PaymentSerializer, PaymentCreateSerializer,
    DriverSerializer, BusLocationSerializer,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _require_admin(request):
    if not request.user.is_staff:
        return Response({"error": "Admin access required."}, status=status.HTTP_403_FORBIDDEN)
    return None


def _require_superuser(request):
    if not request.user.is_superuser:
        return Response({"error": "Super Admin access required."}, status=status.HTTP_403_FORBIDDEN)
    return None


def _get_company(user):
    """Return the company associated with this staff user, or None (sees all)."""
    if user.is_superuser:
        return None
    try:
        return user.profile.company  # None if not set
    except Exception:
        return None


def _company_filter(qs, user, field='company'):
    """Filter queryset by company.
    - Superuser → sees everything
    - Staff with company → sees only their company's data
    - Staff without company → sees nothing (prevents cross-company leaks)
    """
    if user.is_superuser:
        return qs
    company = _get_company(user)
    return qs.filter(**{field: company})


# ─────────────────────────────────────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    username = request.data.get('username', '').strip()
    email    = request.data.get('email', '').strip()
    password = request.data.get('password', '')
    phone    = request.data.get('phone', '').strip()

    if not username or not email or not password:
        return Response({"error": "username, email, and password are required."},
                        status=status.HTTP_400_BAD_REQUEST)
    if len(password) < 8:
        return Response({"error": "Password must be at least 8 characters."},
                        status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(username=username).exists():
        return Response({"error": "Username already exists."},
                        status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(email=email).exists():
        return Response({"error": "Email already registered."},
                        status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.create_user(username=username, email=email, password=password)
    if phone:
        UserProfile.objects.update_or_create(user=user, defaults={"phone": phone})

    return Response({"message": "User created successfully.", "user_id": str(user.id)},
                    status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# USER
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile(request):
    return Response(UserSerializer(request.user).data)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    phone = request.data.get('phone', '').strip()
    email = request.data.get('email', '').strip()

    if email:
        if User.objects.exclude(pk=request.user.pk).filter(email=email).exists():
            return Response({"error": "Email already in use."}, status=status.HTTP_400_BAD_REQUEST)
        request.user.email = email
        request.user.save(update_fields=['email'])

    if phone:
        UserProfile.objects.update_or_create(
            user=request.user, defaults={"phone": phone}
        )
    return Response(UserSerializer(request.user).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def booking_history(request):
    # Only return confirmed or cancelled bookings — PENDING means payment was never completed
    bookings = (
        Booking.objects.filter(user=request.user, status__in=['BOOKED', 'CANCELLED'])
        .select_related('trip__bus', 'trip__route', 'trip__driver')
        .prefetch_related('booking_seats__seat', 'booking_seats__passenger')
        .order_by('-created_at')
    )
    return Response(BookingSerializer(bookings, many=True).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reset_password(request):
    old_password = request.data.get('old_password', '')
    new_password = request.data.get('new_password', '')

    if not request.user.check_password(old_password):
        return Response({"error": "Current password is incorrect."},
                        status=status.HTTP_400_BAD_REQUEST)
    if len(new_password) < 8:
        return Response({"error": "New password must be at least 8 characters."},
                        status=status.HTTP_400_BAD_REQUEST)

    request.user.set_password(new_password)
    request.user.save()
    return Response({"message": "Password updated successfully."})


# ─────────────────────────────────────────────────────────────────────────────
# BUS / ROUTE / TRIP DISCOVERY (public)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def routes(request):
    return Response(RouteSerializer(Route.objects.all(), many=True).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def buses(request):
    return Response(BusSerializer(Bus.objects.filter(is_active=True), many=True).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def trips(request):
    source      = request.GET.get('source', '').strip()
    destination = request.GET.get('destination', '').strip()
    date_filter = request.GET.get('date')

    qs = (
        Trip.objects
        .filter(is_active=True, departure_time__gte=timezone.now())
        .select_related('bus', 'route', 'driver')
    )
    if source:
        qs = qs.filter(route__source__icontains=source)
    if destination:
        qs = qs.filter(route__destination__icontains=destination)
    if date_filter:
        qs = qs.filter(departure_time__date=date_filter)

    return Response(TripSerializer(qs, many=True).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def trip_detail(request, trip_id):
    try:
        trip = Trip.objects.select_related('bus', 'route', 'driver').get(
            id=trip_id, is_active=True
        )
    except Trip.DoesNotExist:
        return Response({"error": "Trip not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(TripSerializer(trip).data)


@api_view(['GET'])
@permission_classes([AllowAny])
def seats(request, trip_id):
    if not Trip.objects.filter(id=trip_id, is_active=True).exists():
        return Response({"error": "Trip not found."}, status=status.HTTP_404_NOT_FOUND)
    data = SeatAvailability.objects.filter(trip_id=trip_id).select_related('seat')
    return Response(SeatAvailabilitySerializer(data, many=True).data)


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE STOPS (public)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def route_stops(request, route_id):
    """Return all intermediate stops for a route (source → stop1 → … → destination)."""
    try:
        route = Route.objects.get(id=route_id)
    except Route.DoesNotExist:
        return Response({"error": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

    stops = RouteStop.objects.filter(route=route).order_by('order')
    return Response(RouteStopSerializer(stops, many=True).data)


# ─────────────────────────────────────────────────────────────────────────────
# BOOKING
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def book(request):
    serializer = BookingCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    vd         = serializer.validated_data
    trip       = vd['trip']
    seat_ids   = vd['seat_ids']
    passengers = vd.get('passengers', [])
    from_stop  = vd.get('from_stop')
    to_stop    = vd.get('to_stop')

    passenger_map = {str(p['seat_id']): p for p in passengers}

    # Release any stale PENDING bookings this user has for the same trip
    # (happens when user went back from payment step without completing payment)
    stale_bookings = Booking.objects.filter(user=request.user, trip=trip, status='PENDING')
    for stale in stale_bookings:
        _delete_pending_booking(stale)

    with transaction.atomic():
        seat_availabilities = list(
            SeatAvailability.objects
            .filter(trip=trip, seat_id__in=seat_ids, is_booked=False)
        )
        if len(seat_availabilities) != len(seat_ids):
            return Response(
                {"error": "Some seats were just booked. Please refresh and try again."},
                status=status.HTTP_409_CONFLICT,
            )

        # Age-based fare calculation per seat
        fare_per_seat = {}
        for sa in seat_availabilities:
            p_data = passenger_map.get(str(sa.seat_id))
            if p_data:
                fare_per_seat[str(sa.seat_id)] = _calc_fare(trip.price, p_data['age'], trip)
            else:
                fare_per_seat[str(sa.seat_id)] = float(trip.price)

        total_amount = round(sum(fare_per_seat.values()), 2)

        booking = Booking.objects.create(
            user=request.user,
            trip=trip,
            total_amount=total_amount,
            status='PENDING',
            from_stop=from_stop,
            to_stop=to_stop,
        )

        booking_seats_list = []
        for sa in seat_availabilities:
            sa.is_booked = True
            booking_seats_list.append(BookingSeat(booking=booking, seat=sa.seat))

        SeatAvailability.objects.bulk_update(seat_availabilities, ['is_booked'])
        BookingSeat.objects.bulk_create(booking_seats_list)

        # Save passenger details with individual fare
        if passenger_map:
            for bs in BookingSeat.objects.filter(booking=booking):
                p_data = passenger_map.get(str(bs.seat_id))
                if p_data:
                    PassengerDetail.objects.create(
                        booking_seat=bs,
                        name=p_data['name'],
                        age=p_data['age'],
                        gender=p_data['gender'],
                        fare=fare_per_seat.get(str(bs.seat_id), float(trip.price)),
                    )

        # Build price breakdown for response
        price_breakdown = []
        for sa in seat_availabilities:
            p_data = passenger_map.get(str(sa.seat_id))
            fare   = fare_per_seat[str(sa.seat_id)]
            age    = p_data['age'] if p_data else None
            if age is None:
                tier = 'adult'
            elif age < 5:
                tier = 'infant'
            elif age < trip.child_max_age:
                tier = 'child'
            elif age >= trip.senior_min_age:
                tier = 'senior'
            else:
                tier = 'adult'
            price_breakdown.append({
                'name': p_data['name'] if p_data else '—',
                'age':  age,
                'tier': tier,
                'fare': fare,
            })

    return Response(
        {
            "message": "Booking created successfully.",
            "booking_id":       str(booking.id),
            "total_amount":     str(total_amount),
            "price_breakdown":  price_breakdown,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def cancel_booking(request, booking_id):
    try:
        booking = Booking.objects.select_related('trip').get(id=booking_id, user=request.user)
    except Booking.DoesNotExist:
        return Response({"error": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.status == 'CANCELLED':
        return Response({"error": "Booking is already cancelled."},
                        status=status.HTTP_400_BAD_REQUEST)

    # Calculate cancellation charge (#10)
    charge_pct         = booking.trip.cancellation_charge_pct
    cancellation_charge = round(booking.total_amount * charge_pct / 100, 2)
    refund_amount       = round(booking.total_amount - cancellation_charge, 2)

    with transaction.atomic():
        seat_ids = list(BookingSeat.objects.filter(booking=booking).values_list('seat_id', flat=True))
        SeatAvailability.objects.filter(trip=booking.trip, seat_id__in=seat_ids).update(is_booked=False)
        booking.status = 'CANCELLED'
        booking.save()

    return Response({
        "message": "Booking cancelled successfully.",
        "cancellation_charge": str(cancellation_charge),
        "refund_amount": str(refund_amount),
    })


# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP TICKET
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def whatsapp_ticket(request, booking_id):
    try:
        booking = (
            Booking.objects
            .select_related('trip__bus', 'trip__route', 'trip__driver',
                            'from_stop', 'to_stop')
            .prefetch_related('booking_seats__seat', 'booking_seats__passenger')
            .get(id=booking_id, user=request.user)
        )
    except Booking.DoesNotExist:
        return Response({"error": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    trip  = booking.trip
    seats = [bs.seat.seat_number for bs in booking.booking_seats.all()]

    dep = trip.departure_time.strftime('%d %b %Y, %I:%M %p')
    arr = trip.arrival_time.strftime('%d %b %Y, %I:%M %p')

    from_lbl = booking.from_stop.name if booking.from_stop else trip.route.source
    to_lbl   = booking.to_stop.name   if booking.to_stop   else trip.route.destination

    message = (
        f"*BusGo Booking Confirmation* ✅\n\n"
        f"Booking ID: #{str(booking.id)[:8].upper()}\n"
        f"Bus: {trip.bus.name} ({trip.bus.bus_number})\n"
        f"Route: {from_lbl} → {to_lbl}\n"
        f"Departure: {dep}\n"
        f"Arrival:   {arr}\n"
        f"Seats: {', '.join(seats)}\n"
        f"Amount: ₹{booking.total_amount}\n"
        f"Status: {booking.status}\n\n"
        f"Thank you for choosing BusGo!"
    )

    import urllib.parse, re
    encoded = urllib.parse.quote(message)

    phone = ''
    try:
        raw = booking.user.profile.phone or ''
        # Strip everything except digits (removes +, spaces, dashes, brackets)
        phone = re.sub(r'\D', '', raw)
        # If Indian number without country code, prepend 91
        if phone and not phone.startswith('91') and len(phone) == 10:
            phone = '91' + phone
    except UserProfile.DoesNotExist:
        pass

    wa_url = f"https://wa.me/{phone}?text={encoded}" if phone else f"https://wa.me/?text={encoded}"
    return Response({"whatsapp_url": wa_url, "message": message})


# ─────────────────────────────────────────────────────────────────────────────
# LIVE BUS TRACKING
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def live_tracking(request, trip_id):
    try:
        location = BusLocation.objects.get(trip_id=trip_id)
    except BusLocation.DoesNotExist:
        return Response({
            "trip_id": trip_id,
            "latitude": 28.6139, "longitude": 77.2090,
            "speed_kmph": 0, "updated_at": None,
        })
    return Response(BusLocationSerializer(location).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_tracking(request, trip_id):
    err = _require_admin(request)
    if err:
        return err
    try:
        trip = Trip.objects.get(id=trip_id)
    except Trip.DoesNotExist:
        return Response({"error": "Trip not found."}, status=status.HTTP_404_NOT_FOUND)

    lat   = request.data.get('latitude')
    lng   = request.data.get('longitude')
    speed = request.data.get('speed_kmph', 0)
    if lat is None or lng is None:
        return Response({"error": "latitude and longitude are required."},
                        status=status.HTTP_400_BAD_REQUEST)

    location, _ = BusLocation.objects.update_or_create(
        trip=trip,
        defaults={"latitude": lat, "longitude": lng, "speed_kmph": speed},
    )
    return Response(BusLocationSerializer(location).data)


# ─────────────────────────────────────────────────────────────────────────────
# DRIVER MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def driver_list(request):
    if request.method == 'GET':
        # #6: filter by company for non-superusers
        qs = _company_filter(Driver.objects.all(), request.user)
        return Response(DriverSerializer(qs, many=True).data)

    err = _require_admin(request)
    if err:
        return err

    serializer = DriverSerializer(data=request.data)
    if serializer.is_valid():
        # Attach company to the new driver if admin has one
        company = _get_company(request.user)
        driver = serializer.save(company=company) if company else serializer.save()
        return Response(DriverSerializer(driver).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def driver_detail(request, driver_id):
    try:
        driver = Driver.objects.get(id=driver_id)
    except Driver.DoesNotExist:
        return Response({"error": "Driver not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(DriverSerializer(driver).data)

    err = _require_admin(request)
    if err:
        return err

    if request.method in ('PUT', 'PATCH'):
        serializer = DriverSerializer(driver, data=request.data,
                                       partial=(request.method == 'PATCH'))
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    driver.delete()
    return Response({"message": "Driver deleted."}, status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────────────────
# RAZORPAY PAYMENT
# ─────────────────────────────────────────────────────────────────────────────

def _razorpay_client():
    return razorpay.Client(auth=(settings.RAZORPAY_KEY, settings.RAZORPAY_SECRET))


def _calc_fare(base_price, age, trip):
    """Return fare for one passenger based on age tier."""
    base = float(base_price)
    if age < 5:
        return 0.0                                                   # Infant — free
    if age < trip.child_max_age:
        return round(base * float(trip.child_fare_pct) / 100, 2)    # Child
    if age >= trip.senior_min_age:
        return round(base * float(trip.senior_fare_pct) / 100, 2)   # Senior
    return base                                                       # Adult


def _build_ticket_message(booking):
    trip     = booking.trip
    seats    = [bs.seat.seat_number for bs in booking.booking_seats.select_related('seat').all()]
    dep      = trip.departure_time.strftime('%d %b %Y, %I:%M %p')
    arr      = trip.arrival_time.strftime('%d %b %Y, %I:%M %p')
    from_lbl = booking.from_stop.name if booking.from_stop else trip.route.source
    to_lbl   = booking.to_stop.name   if booking.to_stop   else trip.route.destination
    return (
        f"*BusGo Booking Confirmed* \u2705\n\n"
        f"Booking ID: #{str(booking.id)[:8].upper()}\n"
        f"Bus: {trip.bus.name} ({trip.bus.bus_number})\n"
        f"Route: {from_lbl} \u2192 {to_lbl}\n"
        f"Departure: {dep}\n"
        f"Arrival:   {arr}\n"
        f"Seats: {', '.join(seats)}\n"
        f"Amount Paid: Rs.{booking.total_amount}\n\n"
        f"Thank you for travelling with BusGo!"
    )


def _send_whatsapp(phone, message):
    """Auto-send WhatsApp via Twilio. Returns True on success, False if unconfigured/failed."""
    import re
    sid   = getattr(settings, 'TWILIO_ACCOUNT_SID',    '')
    token = getattr(settings, 'TWILIO_AUTH_TOKEN',     '')
    from_ = getattr(settings, 'TWILIO_WHATSAPP_FROM',  '')
    # Normalise phone: digits only, prepend 91 for bare 10-digit Indian numbers
    clean = re.sub(r'\D', '', phone or '')
    if clean and not clean.startswith('91') and len(clean) == 10:
        clean = '91' + clean
    if not all([sid, token, from_, clean]):
        return False
    try:
        from twilio.rest import Client
        Client(sid, token).messages.create(
            from_=from_,
            to=f'whatsapp:+{clean}',
            body=message,
        )
        return True
    except Exception:
        return False


def _delete_pending_booking(booking):
    """Release seats and delete a PENDING booking (called on payment failure)."""
    if booking.status == 'BOOKED':
        return   # never delete a paid booking
    with transaction.atomic():
        seat_ids = list(booking.booking_seats.values_list('seat_id', flat=True))
        SeatAvailability.objects.filter(
            trip=booking.trip, seat_id__in=seat_ids
        ).update(is_booked=False)
        booking.delete()


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    serializer = PaymentCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    booking = serializer.validated_data['booking']
    if booking.user != request.user:
        return Response({"error": "Unauthorized."}, status=status.HTTP_403_FORBIDDEN)

    client = _razorpay_client()
    order  = client.order.create({
        "amount": int(booking.total_amount * 100),
        "currency": "INR",
        "payment_capture": 1,
    })
    Payment.objects.update_or_create(
        booking=booking,
        defaults={"razorpay_order_id": order['id'],
                  "amount": booking.total_amount, "status": "PENDING"},
    )
    return Response({
        **order,
        'razorpay_key':         settings.RAZORPAY_KEY,
        'razorpay_merchant_id': settings.RAZORPAY_MERCHANT_ID,
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_payment(request):
    data                = request.data
    razorpay_order_id   = data.get('razorpay_order_id')
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_signature  = data.get('razorpay_signature')
    booking_id          = data.get('booking_id')

    if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature, booking_id]):
        return Response({"error": "Missing required payment fields."},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        _razorpay_client().utility.verify_payment_signature({
            'razorpay_order_id':   razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature':  razorpay_signature,
        })
    except razorpay.errors.SignatureVerificationError:
        return Response({"error": "Payment signature verification failed."},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)
    except Booking.DoesNotExist:
        return Response({"error": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    with transaction.atomic():
        booking.status = 'BOOKED'
        booking.save()
        Payment.objects.update_or_create(
            booking=booking,
            defaults={
                "razorpay_order_id": razorpay_order_id,
                "transaction_id":    razorpay_payment_id,
                "amount":            booking.total_amount,
                "status":            "SUCCESS",
            },
        )

    # Auto-send WhatsApp ticket
    try:
        phone   = booking.user.profile.phone or ''
        message = _build_ticket_message(
            Booking.objects.select_related('trip__bus', 'trip__route', 'from_stop', 'to_stop')
                           .prefetch_related('booking_seats__seat')
                           .get(id=booking.id)
        )
        _send_whatsapp(phone, message)
    except Exception:
        pass

    return Response({"message": "Payment verified successfully."})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def payment_failure(request):
    """Called by frontend on payment failure — deletes the PENDING booking."""
    booking_id = request.data.get('booking_id')
    if not booking_id:
        return Response({"error": "booking_id required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)
    except Booking.DoesNotExist:
        return Response({"error": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.status == 'BOOKED':
        return Response({"error": "Cannot delete a confirmed booking."}, status=status.HTTP_400_BAD_REQUEST)

    _delete_pending_booking(booking)
    return Response({"message": "Booking removed and seats released."})


@api_view(['POST'])
@permission_classes([AllowAny])
def razorpay_webhook(request):
    """Razorpay sends signed POST events here. Verify signature then process."""
    import hmac, hashlib, json

    webhook_secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')
    if webhook_secret:
        received_sig = request.headers.get('X-Razorpay-Signature', '')
        body         = request.body
        expected_sig = hmac.new(webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_sig, received_sig):
            return Response({"error": "Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        payload = json.loads(request.body)
    except Exception:
        return Response({"error": "Invalid JSON."}, status=status.HTTP_400_BAD_REQUEST)

    event   = payload.get('event', '')
    entity  = payload.get('payload', {}).get('payment', {}).get('entity', {})
    order_id = entity.get('order_id')

    if not order_id:
        return Response({"status": "ignored"})

    try:
        payment = Payment.objects.select_related('booking__user__profile').get(
            razorpay_order_id=order_id
        )
    except Payment.DoesNotExist:
        return Response({"status": "unknown order"})

    booking = payment.booking

    if event == 'payment.captured':
        with transaction.atomic():
            booking.status         = 'BOOKED'
            booking.save()
            payment.status         = 'SUCCESS'
            payment.transaction_id = entity.get('id', '')
            payment.save()

        # Auto-send WhatsApp
        try:
            phone   = booking.user.profile.phone or ''
            message = _build_ticket_message(
                Booking.objects.select_related('trip__bus', 'trip__route', 'from_stop', 'to_stop')
                               .prefetch_related('booking_seats__seat')
                               .get(id=booking.id)
            )
            _send_whatsapp(phone, message)
        except Exception:
            pass

    elif event == 'payment.failed':
        with transaction.atomic():
            payment.status = 'FAILED'
            payment.save()
        _delete_pending_booking(booking)

    return Response({"status": "ok"})


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — DASHBOARD / STATS
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_dashboard(request):
    err = _require_admin(request)
    if err:
        return err

    today = date.today()

    def bq():
        return _company_filter(Booking.objects.all(), request.user, field='trip__bus__company')

    total_users    = User.objects.filter(is_staff=False, is_superuser=False).count()
    total_bookings = bq().count()
    total_buses    = _company_filter(Bus.objects.filter(is_active=True), request.user).count()
    total_drivers  = _company_filter(Driver.objects.filter(is_active=True), request.user).count()
    total_tickets  = BookingSeat.objects.filter(
        booking__in=bq().values_list('id', flat=True)
    ).count()
    total_revenue  = (
        bq().filter(status='BOOKED')
        .aggregate(r=Sum('total_amount'))['r'] or 0
    )
    today_bookings = bq().filter(created_at__date=today).count()
    today_revenue  = (
        bq().filter(status='BOOKED', created_at__date=today)
        .aggregate(r=Sum('total_amount'))['r'] or 0
    )

    return Response({
        "users":          total_users,
        "bookings":       total_bookings,
        "buses":          total_buses,
        "drivers":        total_drivers,
        "tickets":        total_tickets,
        "revenue":        str(total_revenue),
        "today_bookings": today_bookings,
        "today_revenue":  str(today_revenue),
        "company":        CompanySerializer(_get_company(request.user)).data
                          if _get_company(request.user) else None,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_bookings(request):
    err = _require_admin(request)
    if err:
        return err

    bookings = _company_filter(
        Booking.objects
        .select_related('user__profile', 'trip__bus', 'trip__route', 'trip__driver',
                        'from_stop', 'to_stop')
        .prefetch_related('booking_seats__seat', 'booking_seats__passenger')
        .order_by('-created_at'),
        request.user,
        field='trip__bus__company',
    )
    return Response(BookingSerializer(bookings, many=True).data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def admin_trips(request):
    err = _require_admin(request)
    if err:
        return err

    qs = _company_filter(
        Trip.objects.select_related('bus', 'route', 'driver'),
        request.user,
        field='bus__company',
    ).order_by('departure_time')
    return Response(TripSerializer(qs, many=True).data)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — BOOK (walk-in / manual booking)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_book(request):
    """Admin manually creates a booking (e.g. walk-in customer at counter)."""
    err = _require_admin(request)
    if err:
        return err

    serializer = BookingCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    vd         = serializer.validated_data
    trip       = vd['trip']
    seat_ids   = vd['seat_ids']
    passengers = vd.get('passengers', [])
    from_stop  = vd.get('from_stop')
    to_stop    = vd.get('to_stop')

    # Use specified customer user_id or fall back to admin user
    booking_user = request.user
    user_id = request.data.get('user_id')
    if user_id:
        try:
            booking_user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            pass

    with transaction.atomic():
        seat_availabilities = list(
            SeatAvailability.objects
            .filter(trip=trip, seat_id__in=seat_ids, is_booked=False)
        )
        if len(seat_availabilities) != len(seat_ids):
            return Response(
                {"error": "Some seats were just booked. Please refresh."},
                status=status.HTTP_409_CONFLICT,
            )

        total_amount = trip.price * len(seat_ids)
        booking = Booking.objects.create(
            user=booking_user,
            trip=trip,
            total_amount=total_amount,
            status='BOOKED',       # Admin bookings are immediately confirmed
            from_stop=from_stop,
            to_stop=to_stop,
        )

        bs_list = []
        for sa in seat_availabilities:
            sa.is_booked = True
            bs_list.append(BookingSeat(booking=booking, seat=sa.seat))

        SeatAvailability.objects.bulk_update(seat_availabilities, ['is_booked'])
        BookingSeat.objects.bulk_create(bs_list)

        passenger_map = {str(p['seat_id']): p for p in passengers}
        if passenger_map:
            for bs in BookingSeat.objects.filter(booking=booking):
                p_data = passenger_map.get(str(bs.seat_id))
                if p_data:
                    PassengerDetail.objects.create(
                        booking_seat=bs,
                        name=p_data['name'],
                        age=p_data['age'],
                        gender=p_data['gender'],
                    )

    return Response(
        {
            "message": "Booking confirmed.",
            "booking_id": str(booking.id),
            "total_amount": str(total_amount),
        },
        status=status.HTTP_201_CREATED,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — BUS MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

def _make_seats(bus):
    """Auto-create seats for a newly registered bus."""
    is_sleeper = bus.bus_type == 'SLEEPER'
    seats = []
    total = bus.total_seats

    if is_sleeper:
        per_deck = total // 2
        for deck in ('LOWER', 'UPPER'):
            prefix = 'L' if deck == 'LOWER' else 'U'
            for n in range(1, per_deck + 1):
                seats.append(Seat(
                    bus=bus, seat_number=f"{prefix}{n}",
                    seat_type='SLEEPER', deck=deck,
                ))
    else:
        rows    = "ABCDEFGHIJ"
        per_row = 4
        num_rows = total // per_row
        for r in range(num_rows):
            row_letter = rows[r] if r < len(rows) else str(r + 1)
            for col in range(1, per_row + 1):
                seat_type = "WINDOW" if col in (1, 4) else "AISLE"
                seats.append(Seat(bus=bus, seat_number=f"{row_letter}{col}",
                                  seat_type=seat_type))
        if total % per_row:
            remaining  = total % per_row
            row_letter = rows[num_rows] if num_rows < len(rows) else str(num_rows + 1)
            for col in range(1, remaining + 1):
                seat_type = "WINDOW" if col in (1, remaining) else "AISLE"
                seats.append(Seat(bus=bus, seat_number=f"{row_letter}{col}",
                                  seat_type=seat_type))

    Seat.objects.bulk_create(seats)
    return len(seats)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def admin_bus_list(request):
    err = _require_admin(request)
    if err:
        return err

    if request.method == 'GET':
        qs = _company_filter(Bus.objects.all().order_by('name'), request.user)
        return Response(BusSerializer(qs, many=True).data)

    serializer = BusSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # Attach company to the new bus if admin has one
    company = _get_company(request.user)
    bus = serializer.save(company=company) if company else serializer.save()
    seat_count = _make_seats(bus)
    data = BusSerializer(bus).data
    data['seats_created'] = seat_count
    return Response(data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def admin_bus_detail(request, bus_id):
    err = _require_admin(request)
    if err:
        return err
    try:
        bus = Bus.objects.get(id=bus_id)
    except Bus.DoesNotExist:
        return Response({"error": "Bus not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(BusSerializer(bus).data)

    if request.method in ('PUT', 'PATCH'):
        serializer = BusSerializer(bus, data=request.data,
                                    partial=(request.method == 'PATCH'))
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    bus.is_active = False
    bus.save()
    return Response({"message": "Bus deactivated."})


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — TRIP MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_trip_create(request):
    err = _require_admin(request)
    if err:
        return err

    bus_id    = request.data.get('bus_id')
    route_id  = request.data.get('route_id')
    driver_id = request.data.get('driver_id')
    dep       = request.data.get('departure_time')
    arr       = request.data.get('arrival_time')
    price     = request.data.get('price')

    if not all([bus_id, route_id, dep, arr, price]):
        return Response(
            {"error": "bus_id, route_id, departure_time, arrival_time and price are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        bus   = Bus.objects.get(id=bus_id)
        route = Route.objects.get(id=route_id)
    except Bus.DoesNotExist:
        return Response({"error": "Bus not found."}, status=status.HTTP_404_NOT_FOUND)
    except Route.DoesNotExist:
        return Response({"error": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

    driver = None
    if driver_id:
        try:
            driver = Driver.objects.get(id=driver_id)
        except Driver.DoesNotExist:
            pass

    trip = Trip.objects.create(
        bus=bus, route=route, driver=driver,
        departure_time=dep, arrival_time=arr,
        price=price, is_active=True,
    )
    return Response(TripSerializer(trip).data, status=status.HTTP_201_CREATED)


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def admin_trip_update(request, trip_id):
    err = _require_admin(request)
    if err:
        return err
    try:
        trip = Trip.objects.select_related('bus', 'route', 'driver').get(id=trip_id)
    except Trip.DoesNotExist:
        return Response({"error": "Trip not found."}, status=status.HTTP_404_NOT_FOUND)

    if 'price' in request.data:
        trip.price = request.data['price']
    if 'is_active' in request.data:
        trip.is_active = request.data['is_active']
    trip.save()
    return Response(TripSerializer(trip).data)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — ROUTE MANAGEMENT + STOPS
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def admin_route_list(request):
    err = _require_admin(request)
    if err:
        return err

    if request.method == 'GET':
        qs = _company_filter(Route.objects.all(), request.user)
        return Response(RouteSerializer(qs, many=True).data)

    serializer = RouteSerializer(data=request.data)
    if serializer.is_valid():
        company = _get_company(request.user)
        route = serializer.save(company=company) if company else serializer.save()
        return Response(RouteSerializer(route).data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def admin_route_stops(request, route_id):
    """GET / POST / DELETE stops for a route — admin only."""
    err = _require_admin(request)
    if err:
        return err

    try:
        route = Route.objects.get(id=route_id)
    except Route.DoesNotExist:
        return Response({"error": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        stops = RouteStop.objects.filter(route=route).order_by('order')
        return Response(RouteStopSerializer(stops, many=True).data)

    if request.method == 'POST':
        name   = request.data.get('name', '').strip()
        order  = request.data.get('order')
        offset = request.data.get('arrival_offset_mins', 0)

        if not name or order is None:
            return Response({"error": "name and order are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        stop = RouteStop.objects.create(
            route=route, name=name, order=int(order),
            arrival_offset_mins=int(offset),
        )
        return Response(RouteStopSerializer(stop).data, status=status.HTTP_201_CREATED)

    # DELETE — remove a specific stop
    stop_id = request.data.get('stop_id')
    if not stop_id:
        return Response({"error": "stop_id required."}, status=status.HTTP_400_BAD_REQUEST)
    deleted, _ = RouteStop.objects.filter(id=stop_id, route=route).delete()
    if deleted:
        return Response({"message": "Stop deleted."})
    return Response({"error": "Stop not found."}, status=status.HTTP_404_NOT_FOUND)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — ROUTE DETAIL (edit/delete a single route)  [Feature #1]
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def admin_route_detail(request, route_id):
    err = _require_admin(request)
    if err:
        return err
    try:
        route = Route.objects.get(id=route_id)
    except Route.DoesNotExist:
        return Response({"error": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(RouteSerializer(route).data)

    if request.method == 'PATCH':
        serializer = RouteSerializer(route, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # DELETE
    route.delete()
    return Response({"message": "Route deleted."}, status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — STOP DETAIL (edit a single stop)  [Feature #1]
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def admin_stop_detail(request, route_id, stop_id):
    err = _require_admin(request)
    if err:
        return err
    try:
        stop = RouteStop.objects.get(id=stop_id, route_id=route_id)
    except RouteStop.DoesNotExist:
        return Response({"error": "Stop not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'PATCH':
        for field in ('name', 'order', 'arrival_offset_mins'):
            if field in request.data:
                setattr(stop, field, request.data[field])
        try:
            stop.save()
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(RouteStopSerializer(stop).data)

    stop.delete()
    return Response({"message": "Stop deleted."}, status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — CANCEL ANY BOOKING  [Feature #5]
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def admin_cancel_booking(request, booking_id):
    err = _require_admin(request)
    if err:
        return err
    try:
        booking = Booking.objects.select_related('trip').get(id=booking_id)
    except Booking.DoesNotExist:
        return Response({"error": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.status == 'CANCELLED':
        return Response({"error": "Booking is already cancelled."},
                        status=status.HTTP_400_BAD_REQUEST)

    # Calculate cancellation charge (#10)
    charge_pct          = booking.trip.cancellation_charge_pct
    cancellation_charge = round(booking.total_amount * charge_pct / 100, 2)
    refund_amount       = round(booking.total_amount - cancellation_charge, 2)

    with transaction.atomic():
        seat_ids = list(BookingSeat.objects.filter(booking=booking).values_list('seat_id', flat=True))
        SeatAvailability.objects.filter(trip=booking.trip, seat_id__in=seat_ids).update(is_booked=False)
        booking.status = 'CANCELLED'
        booking.save()

    return Response({
        "message": "Booking cancelled by admin.",
        "booking_id": str(booking_id),
        "cancellation_charge": str(cancellation_charge),
        "refund_amount": str(refund_amount),
    })


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN — SET CANCELLATION CHARGE for a trip  [Feature #10]
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def admin_trip_cancel_charge(request, trip_id):
    err = _require_admin(request)
    if err:
        return err
    try:
        trip = Trip.objects.get(id=trip_id)
    except Trip.DoesNotExist:
        return Response({"error": "Trip not found."}, status=status.HTTP_404_NOT_FOUND)

    pct = request.data.get('cancellation_charge_pct')
    if pct is None:
        return Response({"error": "cancellation_charge_pct is required."},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        pct = float(pct)
        if not (0 <= pct <= 100):
            raise ValueError
    except (ValueError, TypeError):
        return Response({"error": "cancellation_charge_pct must be 0–100."},
                        status=status.HTTP_400_BAD_REQUEST)

    trip.cancellation_charge_pct = pct
    trip.save()
    return Response({"message": "Cancellation charge updated.", "cancellation_charge_pct": pct})


# ─────────────────────────────────────────────────────────────────────────────
# SUPER ADMIN — COMPANY LIST (for dropdown when assigning to admin)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def admin_my_company(request):
    """GET / PATCH the company assigned to the current admin (non-superuser staff)."""
    err = _require_admin(request)
    if err:
        return err
    company = _get_company(request.user)
    if not company:
        return Response({"error": "No company is assigned to your account."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(CompanySerializer(company).data)

    # PATCH — update allowed fields only
    allowed = {k: v for k, v in request.data.items() if k in ('name', 'phone', 'email', 'address')}
    serializer = CompanySerializer(company, data=allowed, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def admin_companies(request):
    err = _require_superuser(request)
    if err:
        return err

    if request.method == 'GET':
        return Response(CompanySerializer(Company.objects.all(), many=True).data)

    # POST — create company
    serializer = CompanySerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def admin_company_detail(request, company_id):
    err = _require_superuser(request)
    if err:
        return err
    try:
        company = Company.objects.get(id=company_id)
    except Company.DoesNotExist:
        return Response({"error": "Company not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(CompanySerializer(company).data)

    if request.method == 'PATCH':
        serializer = CompanySerializer(company, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    company.delete()
    return Response({"message": "Company deleted."}, status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def superadmin_stats(request):
    """Platform-wide stats for super admin overview."""
    err = _require_superuser(request)
    if err:
        return err
    return Response({
        "companies":   Company.objects.count(),
        "admins":      User.objects.filter(is_staff=True, is_superuser=False).count(),
        "customers":   User.objects.filter(is_staff=False, is_superuser=False).count(),
        "total_users": User.objects.count(),
        "buses":       Bus.objects.filter(is_active=True).count(),
        "trips":       Trip.objects.filter(is_active=True).count(),
        "bookings":    Booking.objects.count(),
        "revenue":     str(Booking.objects.filter(status='BOOKED').aggregate(r=Sum('total_amount'))['r'] or 0),
    })


# ─────────────────────────────────────────────────────────────────────────────
# SUPER ADMIN — USER MANAGEMENT (create/list admin accounts)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def admin_user_list(request):
    err = _require_superuser(request)
    if err:
        return err

    if request.method == 'GET':
        users = User.objects.filter(is_staff=True).select_related('profile__company').order_by('-date_joined')
        return Response(UserSerializer(users, many=True).data)

    # POST — create a new admin account
    username   = request.data.get('username', '').strip()
    email      = request.data.get('email', '').strip()
    password   = request.data.get('password', '').strip()
    phone      = request.data.get('phone', '').strip()
    is_staff   = request.data.get('is_staff', True)
    company_id = request.data.get('company_id')

    if not username or not password:
        return Response({"error": "username and password are required."},
                        status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(username=username).exists():
        return Response({"error": "Username already taken."},
                        status=status.HTTP_400_BAD_REQUEST)

    new_user = User.objects.create_user(username=username, email=email, password=password)
    new_user.is_staff = bool(is_staff)
    new_user.save()

    # Create / update profile
    profile, _ = UserProfile.objects.get_or_create(user=new_user)
    if phone:
        profile.phone = phone
    if company_id:
        try:
            profile.company = Company.objects.get(id=company_id)
        except Company.DoesNotExist:
            pass
    profile.save()

    return Response(UserSerializer(new_user).data, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PATCH', 'DELETE'])
@permission_classes([IsAuthenticated])
def admin_user_detail(request, user_id):
    err = _require_superuser(request)
    if err:
        return err

    try:
        target = User.objects.select_related('profile__company').get(id=user_id)
    except User.DoesNotExist:
        return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        return Response(UserSerializer(target).data)

    if request.method == 'PATCH':
        if 'is_staff' in request.data:
            target.is_staff = bool(request.data['is_staff'])
        if 'is_active' in request.data:
            target.is_active = bool(request.data['is_active'])
        if 'email' in request.data:
            target.email = request.data['email']
        if 'password' in request.data and request.data['password']:
            target.set_password(request.data['password'])
        target.save()

        # Update profile
        profile, _ = UserProfile.objects.get_or_create(user=target)
        if 'phone' in request.data:
            profile.phone = request.data['phone']
        if 'company_id' in request.data:
            cid = request.data['company_id']
            if cid:
                try:
                    profile.company = Company.objects.get(id=cid)
                except Company.DoesNotExist:
                    pass
            else:
                profile.company = None
        profile.save()

        return Response(UserSerializer(target).data)

    # DELETE — soft deactivate to preserve data
    target.is_active = False
    target.save()
    return Response({"message": "User deactivated."})
