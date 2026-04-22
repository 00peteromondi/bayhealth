from .models import User
from hospital.models import HospitalAccess


def _avatar_data(user):
    profile_picture = getattr(user, "profile_picture", None)
    if profile_picture:
        return {"url": profile_picture.url, "alt": user.get_full_name() or user.username}
    return {"url": "", "alt": user.get_full_name() or user.username}


def _link(label, icon, url, request):
    if url == "/":
        is_active = request.path == url
    else:
        is_active = request.path.startswith(url)
    return {
        "label": label,
        "icon": icon,
        "url": url,
        "active": is_active,
    }


def _role_footer_summary(role):
    role_summary = {
        HospitalAccess.Role.OWNER: "Hospital owner access for facility oversight, staff, patients, and shared care coordination.",
        HospitalAccess.Role.ADMIN: "Hospital admin access for staff, patients, hospital setup, and access management.",
        User.Role.PATIENT: "Patient access for appointments, records, medicines, and emergency requests.",
        User.Role.DOCTOR: "Clinical access for appointments, documentation, telemedicine, and notifications.",
        User.Role.NURSE: "Ward access for observations, admissions, and bedside care activity.",
        User.Role.RECEPTIONIST: "Front-desk access for registration, scheduling, and queue flow.",
        User.Role.LAB_TECHNICIAN: "Laboratory access for requests, result entry, and reporting.",
        User.Role.COUNSELOR: "Behavioral health access for sessions, mood logs, and support resources.",
        User.Role.PHARMACIST: "Pharmacy access for orders, stock, dispensing, and refill support.",
        User.Role.EMERGENCY_OPERATOR: "Emergency dispatch access for ambulance requests and live response cases.",
        HospitalAccess.Role.EMERGENCY_OPERATOR: "Emergency dispatch access for ambulance requests, hospital response, and patient transfer coordination.",
        User.Role.ADMIN: "System oversight across clinical, operational, and support services.",
    }
    return role_summary.get(role, "Secure access across BayAfya care services.")


def navigation(request):
    desktop_nav_primary = []
    desktop_nav_group = []
    desktop_nav_sections = []
    mobile_tabs = []
    footer_primary_links = []
    footer_support_links = []
    footer_more_links = []
    shell_visible = True
    current_hospital = None
    current_hospital_label = ""
    hospital_accesses = []

    resolver = getattr(request, "resolver_match", None)
    if resolver and resolver.url_name in {
        "login",
        "register",
        "password_reset",
        "password_reset_done",
        "password_reset_confirm",
        "password_reset_complete",
    }:
        shell_visible = False

    if request.user.is_authenticated:
        hospital_accesses = list(
            HospitalAccess.objects.select_related("hospital").filter(
                user=request.user,
                hospital__is_active=True,
                status=HospitalAccess.Status.ACTIVE,
            )
        )
        hospital_id = request.session.get("current_hospital_id")
        if hospital_id:
            current_hospital = next((access.hospital for access in hospital_accesses if access.hospital_id == hospital_id), None)
        if current_hospital is None and hospital_accesses:
            current_hospital = next((access.hospital for access in hospital_accesses if access.is_primary), hospital_accesses[0].hospital)
        if current_hospital is not None:
            current_hospital_label = current_hospital.name[:6]
        current_hospital_access = next((access for access in hospital_accesses if access.hospital_id == getattr(current_hospital, "id", None)), None) if current_hospital else None
    else:
        current_hospital_access = None

    summary_role = current_hospital_access.role if current_hospital_access else getattr(request.user, "role", None)
    is_clinical_user = getattr(request.user, "role", None) in {
        User.Role.ADMIN,
        User.Role.DOCTOR,
        User.Role.NURSE,
        User.Role.RECEPTIONIST,
        User.Role.LAB_TECHNICIAN,
    } or summary_role in {
        HospitalAccess.Role.OWNER,
        HospitalAccess.Role.ADMIN,
        HospitalAccess.Role.DOCTOR,
        HospitalAccess.Role.NURSE,
        HospitalAccess.Role.RECEPTIONIST,
        HospitalAccess.Role.LAB_TECHNICIAN,
    }

    if request.user.is_authenticated:
        desktop_nav_primary = [
            _link("Hospital", "bi-hospital", "/hospital/dashboard/", request),
            _link("Pharmacy", "bi-capsule-pill", "/pharmacy/", request),
            _link("Ambulance", "bi-truck-front", "/ambulance/request/", request),
        ]
        if request.user.role in {User.Role.PATIENT, User.Role.DOCTOR, User.Role.NURSE, User.Role.RECEPTIONIST, User.Role.LAB_TECHNICIAN, User.Role.COUNSELOR, User.Role.PHARMACIST, User.Role.EMERGENCY_OPERATOR, User.Role.ADMIN}:
            desktop_nav_primary.append(_link("Messages", "bi-chat-dots", "/communications/", request))
        if is_clinical_user:
            clinical_items = [
                _link("Patients", "bi-people", "/hospital/patients/", request),
                _link("Insights", "bi-graph-up-arrow", "/hospital/insights/", request),
                _link("Admissions", "bi-hospital", "/hospital/admissions/", request),
                _link("Surgery", "bi-scissors", "/hospital/surgery/", request),
            ]
            desktop_nav_sections.append(
                {
                    "label": "Clinical Ops",
                    "icon": "bi-clipboard2-pulse",
                    "links": clinical_items,
                    "active": any(item["active"] for item in clinical_items),
                }
            )
        wellness_items = [
            _link("Telemedicine", "bi-camera-video", "/telemedicine/dashboard/", request),
            _link("Mental Health", "bi-flower2", "/mental-health/dashboard/", request),
            _link("Symptom Checker", "bi-clipboard2-pulse", "/symptom-checker/", request),
        ]
        desktop_nav_sections.append(
            {
                "label": "Virtual & Wellness",
                "icon": "bi-heart-pulse",
                "links": wellness_items,
                "active": any(item["active"] for item in wellness_items),
            }
        )

        role_tabs = {
            User.Role.PATIENT: [
                _link("Home", "bi-house-door", "/", request),
                _link("Profile", "bi-person-badge", "/profile/", request),
                _link("Messages", "bi-chat-dots", "/communications/", request),
                _link("Hospital", "bi-buildings", "/hospital/dashboard/", request),
                _link("Check", "bi-clipboard2-pulse", "/symptom-checker/", request),
                _link("Pharmacy", "bi-capsule-pill", "/pharmacy/", request),
                _link("Emergency", "bi-truck-front", "/ambulance/request/", request),
            ],
            User.Role.DOCTOR: [
                _link("Home", "bi-house-door", "/", request),
                _link("Profile", "bi-person-badge", "/profile/", request),
                _link("Hospital", "bi-buildings", "/hospital/dashboard/", request),
                _link("Messages", "bi-chat-dots", "/communications/", request),
                _link("Patients", "bi-people", "/hospital/patients/", request),
                _link("Insights", "bi-graph-up-arrow", "/hospital/insights/", request),
                _link("Admissions", "bi-door-open", "/hospital/admissions/", request),
                _link("Surgery", "bi-scissors", "/hospital/surgery/", request),
                _link("Virtual Care", "bi-camera-video", "/telemedicine/dashboard/", request),
                _link("Alerts", "bi-bell", "/notifications/", request),
            ],
            User.Role.NURSE: [
                _link("Home", "bi-house-door", "/", request),
                _link("Profile", "bi-person-badge", "/profile/", request),
                _link("Hospital", "bi-buildings", "/hospital/dashboard/", request),
                _link("Messages", "bi-chat-dots", "/communications/", request),
                _link("Patients", "bi-people", "/hospital/patients/", request),
                _link("Insights", "bi-graph-up-arrow", "/hospital/insights/", request),
                _link("Admissions", "bi-door-open", "/hospital/admissions/", request),
                _link("Alerts", "bi-bell", "/notifications/", request),
                _link("Pharmacy", "bi-capsule-pill", "/pharmacy/", request),
            ],
            User.Role.RECEPTIONIST: [
                _link("Home", "bi-house-door", "/", request),
                _link("Profile", "bi-person-badge", "/profile/", request),
                _link("Hospital", "bi-buildings", "/hospital/dashboard/", request),
                _link("Messages", "bi-chat-dots", "/communications/", request),
                _link("Patients", "bi-people", "/hospital/patients/", request),
                _link("Insights", "bi-graph-up-arrow", "/hospital/insights/", request),
                _link("Admissions", "bi-door-open", "/hospital/admissions/", request),
                _link("Surgery", "bi-scissors", "/hospital/surgery/", request),
                _link("Alerts", "bi-bell", "/notifications/", request),
                _link("Pharmacy", "bi-capsule-pill", "/pharmacy/", request),
            ],
            User.Role.LAB_TECHNICIAN: [
                _link("Home", "bi-house-door", "/", request),
                _link("Profile", "bi-person-badge", "/profile/", request),
                _link("Hospital", "bi-buildings", "/hospital/dashboard/", request),
                _link("Messages", "bi-chat-dots", "/communications/", request),
                _link("Patients", "bi-people", "/hospital/patients/", request),
                _link("Insights", "bi-graph-up-arrow", "/hospital/insights/", request),
                _link("Admissions", "bi-door-open", "/hospital/admissions/", request),
                _link("Alerts", "bi-bell", "/notifications/", request),
                _link("Pharmacy", "bi-capsule-pill", "/pharmacy/", request),
            ],
            User.Role.COUNSELOR: [
                _link("Home", "bi-house-door", "/", request),
                _link("Profile", "bi-person-badge", "/profile/", request),
                _link("Messages", "bi-chat-dots", "/communications/", request),
                _link("Wellbeing", "bi-flower2", "/mental-health/dashboard/", request),
                _link("Alerts", "bi-bell", "/notifications/", request),
                _link("Hospital", "bi-buildings", "/hospital/dashboard/", request),
            ],
            User.Role.PHARMACIST: [
                _link("Home", "bi-house-door", "/", request),
                _link("Profile", "bi-person-badge", "/profile/", request),
                _link("Messages", "bi-chat-dots", "/communications/", request),
                _link("Pharmacy", "bi-capsule-pill", "/pharmacy/", request),
                _link("Alerts", "bi-bell", "/notifications/", request),
                _link("Hospital", "bi-buildings", "/hospital/dashboard/", request),
            ],
            User.Role.EMERGENCY_OPERATOR: [
                _link("Home", "bi-house-door", "/", request),
                _link("Profile", "bi-person-badge", "/profile/", request),
                _link("Messages", "bi-chat-dots", "/communications/", request),
                _link("Dispatch", "bi-truck-front", "/ambulance/request/", request),
                _link("Alerts", "bi-bell", "/notifications/", request),
                _link("Hospital", "bi-buildings", "/hospital/dashboard/", request),
            ],
            User.Role.ADMIN: [
                _link("Home", "bi-house-door", "/", request),
                _link("Profile", "bi-person-badge", "/profile/", request),
                _link("Hospital", "bi-buildings", "/hospital/dashboard/", request),
                _link("Messages", "bi-chat-dots", "/communications/", request),
                _link("Patients", "bi-people", "/hospital/patients/", request),
                _link("Insights", "bi-graph-up-arrow", "/hospital/insights/", request),
                _link("Admissions", "bi-door-open", "/hospital/admissions/", request),
                _link("Surgery", "bi-scissors", "/hospital/surgery/", request),
                _link("Pharmacy", "bi-capsule-pill", "/pharmacy/", request),
                _link("Alerts", "bi-bell", "/notifications/", request),
            ],
        }
        mobile_tabs = role_tabs.get(request.user.role, role_tabs[User.Role.ADMIN])
        footer_primary_links = mobile_tabs
        footer_support_links = [
            _link("Notifications", "bi-bell", "/notifications/", request),
            _link("Help & Support", "bi-life-preserver", "/support/", request),
            _link("Privacy", "bi-shield-check", "/privacy/", request),
            _link("Logout", "bi-box-arrow-right", "/logout/", request),
        ]
        footer_more_links = [
            _link("Telemedicine", "bi-camera-video", "/telemedicine/dashboard/", request),
            _link("Mental Health", "bi-flower2", "/mental-health/dashboard/", request),
            _link("Symptom Checker", "bi-clipboard2-pulse", "/symptom-checker/", request),
        ]
        desktop_nav_group = desktop_nav_sections[0]["links"] if desktop_nav_sections else []
    else:
        footer_primary_links = [
            _link("Patient portal", "bi-person-heart", "/login/", request),
            _link("Clinical workspace", "bi-hospital", "/login/", request),
            _link("Virtual care", "bi-camera-video", "/login/", request),
            _link("Pharmacy services", "bi-capsule-pill", "/login/", request),
        ]
        footer_more_links = [
            _link("Symptom triage", "bi-clipboard2-pulse", "/login/", request),
            _link("Mental wellness", "bi-flower2", "/login/", request),
            _link("Emergency requests", "bi-truck-front", "/login/", request),
            _link("Hospital insights", "bi-graph-up-arrow", "/login/", request),
        ]
        footer_support_links = [
            _link("Return home", "bi-house-door", "/", request),
            _link("Login", "bi-box-arrow-in-right", "/login/", request),
            _link("Register", "bi-person-plus", "/register/", request),
        ]

    if len(footer_primary_links) > 4:
        footer_more_links = footer_primary_links[4:] + footer_more_links
        footer_primary_links = footer_primary_links[:4]

    return {
        "desktop_nav_links": desktop_nav_primary + [item for section in desktop_nav_sections for item in section["links"]],
        "desktop_nav_primary": desktop_nav_primary,
        "desktop_nav_group": desktop_nav_group,
        "desktop_nav_sections": desktop_nav_sections,
        "desktop_nav_group_active": any(item["active"] for section in desktop_nav_sections for item in section["links"]),
        "mobile_nav_tabs": mobile_tabs,
        "show_shell_chrome": shell_visible,
        "footer_summary": _role_footer_summary(summary_role) if request.user.is_authenticated else "Explore patient access, virtual care, pharmacy, emergency response, and hospital services. Sign in to continue securely into the relevant care workspace.",
        "footer_primary_links": footer_primary_links,
        "footer_support_links": footer_support_links,
        "footer_more_links": footer_more_links,
        "current_hospital": current_hospital,
        "current_hospital_label": current_hospital_label,
        "current_hospital_access": current_hospital_access,
        "hospital_accesses": hospital_accesses,
        "platform_name": "BayAfya",
        "platform_short_name": "BayAfya",
        "invite_welcome_modal": request.session.pop("invite_welcome_modal", None),
        "avatar_data": _avatar_data(request.user) if request.user.is_authenticated else {"url": "", "alt": ""},
    }
