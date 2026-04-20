from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
    register, profile, update_profile, booking_history, reset_password,
    routes, buses, trips, trip_detail, seats,
    book, cancel_booking,
    whatsapp_ticket,
    live_tracking, update_tracking,
    driver_list, driver_detail,
    create_order, verify_payment, payment_failure, razorpay_webhook,
    admin_dashboard, admin_bookings, admin_trips,
    admin_bus_list, admin_bus_detail,
    admin_trip_create, admin_trip_update,
    admin_route_list, admin_route_detail,
    route_stops, admin_route_stops, admin_stop_detail,
    admin_book, admin_cancel_booking,
    admin_trip_cancel_charge,
    admin_companies, admin_company_detail, superadmin_stats, admin_my_company,
    admin_user_list, admin_user_detail,
)

urlpatterns = [
    # Authentication
    path('register/',      register,                     name='register'),
    path('login/',         TokenObtainPairView.as_view(), name='login'),
    path('refresh-token/', TokenRefreshView.as_view(),    name='refresh-token'),

    # User
    path('profile/',         profile,         name='profile'),
    path('profile/update/',  update_profile,  name='update-profile'),
    path('booking-history/', booking_history, name='booking-history'),
    path('reset-password/',  reset_password,  name='reset-password'),

    # Bus & Trip discovery
    path('routes/',              routes,      name='routes'),
    path('buses/',               buses,       name='buses'),
    path('trips/',               trips,       name='trips'),
    path('trips/<str:trip_id>/', trip_detail, name='trip-detail'),

    # Route stops (public)
    path('routes/<str:route_id>/stops/', route_stops, name='route-stops'),

    # Seat availability for a trip
    path('seats/<str:trip_id>/', seats, name='seats'),

    # Booking
    path('book/',                          book,           name='book'),
    path('cancel/<str:booking_id>/',       cancel_booking, name='cancel-booking'),
    path('whatsapp-ticket/<str:booking_id>/', whatsapp_ticket, name='whatsapp-ticket'),

    # Live tracking
    path('tracking/<str:trip_id>/',        live_tracking,   name='live-tracking'),
    path('tracking/update/<str:trip_id>/', update_tracking, name='update-tracking'),

    # Driver management
    path('drivers/',               driver_list,   name='driver-list'),
    path('drivers/<str:driver_id>/', driver_detail, name='driver-detail'),

    # Payment (Razorpay)
    path('create-order/',    create_order,     name='create-order'),
    path('verify-payment/',  verify_payment,   name='verify-payment'),
    path('payment-failure/', payment_failure,  name='payment-failure'),
    path('razorpay-webhook/', razorpay_webhook, name='razorpay-webhook'),

    # Admin — stats
    path('admin-dashboard/', admin_dashboard,  name='admin-dashboard'),
    path('admin/bookings/',  admin_bookings,   name='admin-bookings'),

    # Admin — trips
    path('admin/trips/',               admin_trips,        name='admin-trips'),
    path('admin/trips/create/',        admin_trip_create,  name='admin-trip-create'),
    path('admin/trips/<str:trip_id>/update/', admin_trip_update, name='admin-trip-update'),

    # Admin — buses
    path('admin/buses/',               admin_bus_list,   name='admin-bus-list'),
    path('admin/buses/<str:bus_id>/',  admin_bus_detail, name='admin-bus-detail'),

    # Admin — routes
    path('admin/routes/', admin_route_list, name='admin-route-list'),
    path('admin/routes/<str:route_id>/', admin_route_detail, name='admin-route-detail'),

    # Admin — route stops management
    path('admin/routes/<str:route_id>/stops/', admin_route_stops, name='admin-route-stops'),
    path('admin/routes/<str:route_id>/stops/<str:stop_id>/', admin_stop_detail, name='admin-stop-detail'),

    # Admin — manual booking
    path('admin/book/', admin_book, name='admin-book'),

    # Admin — cancel any booking  [#5]
    path('admin/bookings/<str:booking_id>/cancel/', admin_cancel_booking, name='admin-cancel-booking'),

    # Admin — set cancellation charge on a trip  [#10]
    path('admin/trips/<str:trip_id>/cancel-charge/', admin_trip_cancel_charge, name='admin-trip-cancel-charge'),

    # Super Admin — user management  [#4]
    path('admin/users/',                  admin_user_list,   name='admin-user-list'),
    path('admin/users/<int:user_id>/',    admin_user_detail, name='admin-user-detail'),

    # Admin — edit own company profile
    path('admin/my-company/', admin_my_company, name='admin-my-company'),

    # Super Admin — company management
    path('admin/companies/',                           admin_companies,      name='admin-companies'),
    path('admin/companies/<str:company_id>/',          admin_company_detail, name='admin-company-detail'),
    path('admin/superadmin-stats/',                    superadmin_stats,     name='superadmin-stats'),
]
