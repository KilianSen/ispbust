"""Report text, per language.

Adding a language means adding a key to each entry below -- nothing else in the
renderer is language-aware. English is the fallback for any missing string, so
a partial translation degrades to mixed text rather than a crash.

The register is deliberately flat and factual. A document that argues is easy
to dismiss; a document that counts is not.
"""

from __future__ import annotations

import logging

LOG = logging.getLogger("ispbust.report")

DEFAULT_LANG = "en"

STRINGS: dict = {
    # -- document furniture ------------------------------------------------
    "doc_title": {
        "en": "Connection fault report",
        "de": "Störungsdokumentation Internetanschluss",
    },
    "subtitle": {
        "en": "Measurement period {frm} to {to} ({tz}) · Customer reference: {ref} · Generated {now}",
        "de": "Messzeitraum {frm} bis {to} ({tz}) · Kundenkennung: {ref} · Erstellt am {now}",
    },
    "no_ref": {"en": "not stated", "de": "nicht angegeben"},
    "footer": {
        "en": "Generated with ispbust · Measurement period {frm} to {to} · "
              "All figures come from automated measurements.",
        "de": "Erstellt mit ispbust · Messzeitraum {frm} bis {to} · "
              "Alle Angaben beruhen auf automatisiert erfassten Messwerten.",
    },
    "empty": {"en": "No data in this period.", "de": "Keine Daten im Zeitraum."},

    # -- KPIs ---------------------------------------------------------------
    "kpi_primary_loss": {
        "en": "Packet loss, {label}",
        "de": "Paketverlust, {label}",
    },
    "kpi_control_loss": {
        "en": "Packet loss, reference link ({label}), identical targets",
        "de": "Paketverlust, Referenzleitung ({label}), identische Ziele",
    },
    "kpi_first_hop_loss": {
        "en": "Packet loss to the operator's own first network node",
        "de": "Paketverlust bis zum ersten Netzknoten des Anbieters",
    },
    "kpi_blackout": {
        "en": "Minutes of total outage (100 % loss)",
        "de": "Minuten mit Totalausfall (100 % Verlust)",
    },
    "kpi_events": {
        "en": "Fault events (2 or more consecutive minutes)",
        "de": "Störungsereignisse (2 oder mehr zusammenhängende Minuten)",
    },

    # -- section 1: summary -------------------------------------------------
    "s1_heading": {"en": "Summary", "de": "Zusammenfassung"},
    "s1_method": {
        "en": "The connection was measured continuously and automatically throughout the "
              "period stated above (one ICMP packet per second per target, without "
              "interruption). Measurements were taken from within the customer network "
              "over a connection bound to this link by a routing rule; failover to any "
              "other connection is not possible.",
        "de": "Der Anschluss wurde im genannten Zeitraum durchgehend automatisiert gemessen "
              "(ein ICMP-Paket pro Sekunde je Ziel, ununterbrochen). Gemessen wurde aus dem "
              "Kundennetz heraus über eine Verbindung, die per Routing-Regel fest diesem "
              "Anschluss zugeordnet ist; ein Ausweichen auf eine andere Verbindung ist "
              "ausgeschlossen.",
    },
    "s1_result": {
        "en": "Result: <strong>{loss} packet loss</strong> across {minutes} measured minutes. "
              "The line was completely unusable (100 % loss) for <strong>{blackout} minutes</strong> "
              "and severely degraded ({threshold} loss or more) for <strong>{degraded} minutes</strong>.",
        "de": "Ergebnis: <strong>{loss} Paketverlust</strong> über {minutes} ausgewertete "
              "Messminuten. In <strong>{blackout} Minuten</strong> war die Leitung "
              "vollständig unbenutzbar (100 % Verlust), in <strong>{degraded} Minuten</strong> "
              "stark gestört ({threshold} Verlust oder mehr).",
    },
    "s1_control_title": {
        "en": "Ruling out causes in the customer network.",
        "de": "Abgrenzung gegen Fehlerquellen im Kundennetz.",
    },
    "s1_control_body": {
        "en": "In the same minutes, the same targets were measured in parallel over a "
              "second, independent internet connection ({control}) — from the same local "
              "network, with the same hardware and the same software. In "
              "<strong>{only_bad} of {common} jointly measured minutes</strong> only the "
              "link under test was disrupted while the reference link worked correctly at "
              "that same moment. In {blackout_fine} minutes the link under test was "
              "completely dead while the reference link operated normally. A cause in the "
              "customer network, in the measurement method or in the public internet is "
              "therefore ruled out.",
        "de": "In denselben Minuten wurden dieselben Ziele parallel über einen zweiten, "
              "unabhängigen Internetanschluss ({control}) gemessen — aus demselben lokalen "
              "Netz, mit derselben Hardware und derselben Software. In "
              "<strong>{only_bad} von {common} gemeinsam gemessenen Minuten</strong> war "
              "ausschließlich der geprüfte Anschluss gestört, während die Referenzleitung im "
              "selben Moment einwandfrei arbeitete. In {blackout_fine} Minuten war der "
              "geprüfte Anschluss vollständig tot, während die Referenzleitung normal "
              "funktionierte. Eine Ursache im Kundennetz, in der Messmethode oder im "
              "öffentlichen Internet ist damit ausgeschlossen.",
    },
    "s1_first_hop": {
        "en": "<strong>The fault lies inside the operator's network.</strong> The loss of "
              "{loss} was measured against the operator's own first network node ({hops}) — "
              "that is, still inside their network, before any handover to third parties.",
        "de": "<strong>Die Störung liegt im Netz des Anbieters.</strong> Der Verlust von "
              "{loss} wurde gegen den ersten Netzknoten des Anbieters selbst gemessen "
              "({hops}) — also noch innerhalb des Anbieternetzes, vor jeder Übergabe an "
              "Dritte.",
    },
    "s1_no_control": {
        "en": "No reference link was available for this period, so no side-by-side "
              "comparison is included.",
        "de": "Für diesen Zeitraum stand keine Referenzleitung zur Verfügung; ein direkter "
              "Vergleich ist daher nicht enthalten.",
    },

    # -- section 2: daily ---------------------------------------------------
    "s2_heading": {"en": "Daily breakdown", "de": "Tägliche Auswertung"},
    "chart_daily": {"en": "Packet loss per day", "de": "Täglicher Paketverlust"},
    "legend_primary": {"en": "Link under test", "de": "Geprüfter Anschluss"},
    "legend_control": {"en": "Reference link", "de": "Referenzleitung"},
    "th_day": {"en": "Day", "de": "Tag"},
    "th_minutes": {"en": "Measured minutes", "de": "Messminuten"},
    "th_loss": {"en": "Packet loss", "de": "Paketverlust"},
    "th_degraded": {"en": "Degraded minutes", "de": "Gestörte Minuten"},
    "th_blackout": {"en": "Total outage (min)", "de": "Totalausfall (Min.)"},
    "th_rtt_median": {"en": "RTT median", "de": "RTT Median"},
    "th_control_loss": {"en": "Reference link loss", "de": "Referenzleitung Verlust"},

    # -- section 3: outages -------------------------------------------------
    "s3_heading": {"en": "Fault events", "de": "Störungsereignisse"},
    "s3_intro": {
        "en": "Contiguous periods with at least {threshold} packet loss, longest first. "
              "All times in {tz}.",
        "de": "Zusammenhängende Zeiträume mit mindestens {threshold} Paketverlust, "
              "absteigend nach Dauer. Alle Zeiten in {tz}.",
    },
    "th_start": {"en": "Start", "de": "Beginn"},
    "th_end": {"en": "End", "de": "Ende"},
    "th_duration": {"en": "Duration (min)", "de": "Dauer (Min.)"},
    "th_avg_loss": {"en": "Loss, mean", "de": "Verlust &#8709;"},
    "th_max_loss": {"en": "Loss, max", "de": "Verlust max."},
    "th_control_same_time": {
        "en": "Reference link, same moment",
        "de": "Referenzleitung zeitgleich",
    },
    "s3_more": {
        "en": "A further {count} events are contained in the raw data.",
        "de": "Weitere {count} Ereignisse sind in den Rohdaten enthalten.",
    },

    # -- section 4: daily power cycle --------------------------------------
    "s4_heading": {
        "en": "Relation to the nightly restart of the {device}",
        "de": "Zusammenhang mit dem nächtlichen Neustart des {device}",
    },
    "s4_intro": {
        "en": "The {device} is currently restarted every day at {hour}, because the "
              "connection otherwise degrades progressively over several days. The following "
              "analysis shows packet loss as a function of the time elapsed since that "
              "restart.",
        "de": "Das {device} wird derzeit täglich um {hour} Uhr neu gestartet, weil sich die "
              "Verbindung andernfalls über Tage hinweg zunehmend verschlechtert. Die "
              "folgende Auswertung zeigt den Paketverlust in Abhängigkeit von der seit dem "
              "Neustart vergangenen Zeit.",
    },
    "chart_cycle_axis": {
        "en": "Hours since the nightly restart ({hour} local time)",
        "de": "Stunden seit dem nächtlichen Neustart ({hour} Ortszeit)",
    },
    "th_hours_since": {"en": "Hours after restart", "de": "Stunden nach Neustart"},
    "th_local_time": {"en": "Local time", "de": "Ortszeit"},

    # -- section 5: hour of day --------------------------------------------
    "s5_heading": {"en": "Loss by time of day", "de": "Verlust nach Tageszeit"},
    "s5_intro": {
        "en": "Loss concentrated in the evening peak suggests congestion; loss spread "
              "evenly across the day points at a hardware or line fault.",
        "de": "Ein Verlust, der sich auf die Abendstunden konzentriert, spricht für eine "
              "Überlastung; ein über den Tag gleichmäßig verteilter Verlust spricht für "
              "einen Hardware- oder Leitungsfehler.",
    },
    "chart_hour_axis": {"en": "Local hour of day", "de": "Stunde des Tages (Ortszeit)"},
    "th_hour": {"en": "Hour", "de": "Stunde"},

    # -- section 6: DNS -----------------------------------------------------
    "s6_heading": {"en": "Name resolution (DNS)", "de": "Namensauflösung (DNS)"},
    "s6_intro": {
        "en": "One query was sent to each resolver at a fixed interval. The figures for "
              "public resolvers act as a control: they show whether a fault lies with the "
              "line or with the operator's resolvers.",
        "de": "Je Resolver wurde in festem Abstand eine Abfrage gestellt. Die Werte gegen "
              "öffentliche Resolver dienen als Kontrolle: Sie zeigen, ob eine Störung an "
              "der Leitung oder an den Resolvern des Anbieters liegt.",
    },
    "th_resolver": {"en": "Resolver", "de": "Resolver"},
    "th_role": {"en": "Role", "de": "Rolle"},
    "th_queries": {"en": "Queries", "de": "Abfragen"},
    "th_failures": {"en": "Failures", "de": "Fehlschläge"},
    "th_fail_rate": {"en": "Failure rate", "de": "Fehlerquote"},
    "th_p50": {"en": "Response p50", "de": "Antwortzeit p50"},
    "th_p95": {"en": "Response p95", "de": "Antwortzeit p95"},

    # -- measurement integrity ---------------------------------------------
    "si_heading": {
        "en": "Integrity of the measurement",
        "de": "Integrität der Messung",
    },
    "si_intro": {
        "en": "Throughout the period the probe repeatedly confirmed, against independent "
              "external services, which public address its own traffic arrived from. This "
              "verifies that the measurements below describe the connection named in this "
              "report and not some other one.",
        "de": "Während des gesamten Zeitraums hat die Messsonde wiederholt gegen "
              "unabhängige externe Dienste geprüft, von welcher öffentlichen Adresse ihr "
              "eigener Datenverkehr eintraf. Damit ist belegt, dass sich die folgenden "
              "Messwerte auf den in diesem Bericht genannten Anschluss beziehen und nicht "
              "auf einen anderen.",
    },
    "si_confirmed": {
        "en": "{confirmed} of {graded} checks confirmed the expected connection "
              "({ratio}). Expected range: {expected}.",
        "de": "{confirmed} von {graded} Prüfungen bestätigten den erwarteten Anschluss "
              "({ratio}). Erwarteter Bereich: {expected}.",
    },
    "si_clean": {
        "en": "No deviation was observed at any point in the period.",
        "de": "Im gesamten Zeitraum wurde keine Abweichung festgestellt.",
    },
    "si_leak_title": {
        "en": "Measurements in these periods describe a different connection.",
        "de": "Messwerte in diesen Zeiträumen beziehen sich auf einen anderen Anschluss.",
    },
    "si_leak_body": {
        "en": "During the periods listed below the probe's traffic left by an address "
              "outside the expected range, so the router had moved it to another uplink. "
              "Figures covering these periods do not describe the connection under "
              "investigation and should be disregarded.",
        "de": "In den unten aufgeführten Zeiträumen verließ der Datenverkehr der Messsonde "
              "das Netz über eine Adresse außerhalb des erwarteten Bereichs; der Router "
              "hatte sie auf einen anderen Anschluss umgeleitet. Werte aus diesen "
              "Zeiträumen beschreiben nicht den geprüften Anschluss und sind "
              "unberücksichtigt zu lassen.",
    },
    "si_unknown": {
        "en": "{count} checks could not be completed, which is expected while the "
              "connection is down and is counted separately from both outcomes.",
        "de": "{count} Prüfungen konnten nicht durchgeführt werden. Das ist bei einem "
              "ausgefallenen Anschluss zu erwarten und wird von beiden Ergebnissen "
              "getrennt gezählt.",
    },
    "th_observed_address": {"en": "Observed address", "de": "Beobachtete Adresse"},
    "th_checks": {"en": "Checks", "de": "Prüfungen"},

    # -- reachability by address family ------------------------------------
    "sr_heading": {
        "en": "Reachability by address family",
        "de": "Erreichbarkeit nach Adressfamilie",
    },
    "sr_intro": {
        "en": "A real connection was opened to each site at a fixed interval, separately "
              "over IPv4 and IPv6. Packet loss measurements alone cannot show this: if one "
              "address family is unusable, a browser tries it first and the site fails to "
              "load, while every ping continues to succeed over the other one.",
        "de": "Zu jeder Website wurde in festem Abstand eine echte Verbindung aufgebaut, "
              "getrennt über IPv4 und IPv6. Reine Paketverlustmessungen können das nicht "
              "zeigen: Ist eine Adressfamilie unbrauchbar, versucht ein Browser sie zuerst "
              "und die Seite lädt nicht, während alle Pings über die andere weiterhin "
              "erfolgreich sind.",
    },
    "sr_finding_title": {
        "en": "One address family is unusable.",
        "de": "Eine Adressfamilie ist unbrauchbar.",
    },
    "sr_finding_body": {
        "en": "{host} resolves to {address} over {family}, but {failed} of {attempts} "
              "connection attempts over {family} failed, while {working} worked normally in "
              "the same period. Users experience this as the site not loading at all.",
        "de": "{host} löst über {family} auf {address} auf, jedoch schlugen {failed} von "
              "{attempts} Verbindungsversuchen über {family} fehl, während {working} im "
              "selben Zeitraum einwandfrei funktionierte. Nutzer erleben das als "
              "vollständiges Nichtladen der Seite.",
    },
    "th_site": {"en": "Site", "de": "Website"},
    "th_family": {"en": "Address family", "de": "Adressfamilie"},
    "th_attempts": {"en": "Attempts", "de": "Versuche"},
    "th_failed": {"en": "Failed", "de": "Fehlgeschlagen"},
    "th_connect_avg": {"en": "Connect mean", "de": "Verbindungsaufbau &#8709;"},
    "th_control_family": {"en": "Reference link", "de": "Referenzleitung"},

    # -- section 7: targets -------------------------------------------------
    "s7_heading": {"en": "Individual measurement targets", "de": "Einzelne Messziele"},
    "th_target": {"en": "Target", "de": "Ziel"},
    "th_packets": {"en": "Packets", "de": "Pakete"},
    "th_lost": {"en": "Lost", "de": "Verloren"},
    "th_rtt_avg": {"en": "RTT mean", "de": "RTT &#8709;"},

    # -- section 8: traces --------------------------------------------------
    "s8_heading": {"en": "Path measurements during the fault",
                   "de": "Pfadmessungen während der Störung"},
    "s8_intro": {
        "en": "Path measurements triggered automatically at the moment a fault was "
              "detected. The hop number shows from which network node loss begins.",
        "de": "Automatisch ausgelöste Messungen des Netzpfads im Moment einer erkannten "
              "Störung. Die Hop-Nummer zeigt, ab welchem Netzknoten Verluste auftreten.",
    },
    "th_hop": {"en": "Hop", "de": "Hop"},
    "th_address": {"en": "Address", "de": "Adresse"},
    "th_avg_ms": {"en": "Mean ms", "de": "&#8709; ms"},
    "th_worst_ms": {"en": "Worst ms", "de": "Max. ms"},

    # -- section 9: method --------------------------------------------------
    "s9_heading": {"en": "Method and raw data", "de": "Messmethode und Rohdaten"},
    "s9_method": {
        "en": "Measurement probe: a dedicated system inside the customer network, bound to "
              "this connection by policy routing, with failover disabled. Measurement: "
              "<code>fping</code>, one packet per second per target, evaluated in "
              "{window}-second windows; DNS via <code>dnspython</code>; path measurement via "
              "<code>mtr</code>. All timestamps recorded in UTC and shown here in {tz}. "
              "Clocks synchronised via NTP.",
        "de": "Messsonde: ein dediziertes System im Kundennetz, das per Richtlinien-Routing "
              "fest diesem Anschluss zugeordnet ist, ohne Failover. Messung: "
              "<code>fping</code>, ein Paket pro Sekunde und Ziel, Auswertung in "
              "{window}-Sekunden-Fenstern; DNS über <code>dnspython</code>; Pfadmessung über "
              "<code>mtr</code>. Alle Zeitstempel in UTC erfasst, hier in {tz} dargestellt. "
              "Zeitsynchronisierung über NTP.",
    },
    "s9_raw": {
        "en": "The raw data is retained unaltered as line-delimited JSON and as a SQLite "
              "database, and can be supplied in full on request. The checksums below "
              "identify the exact files this report was generated from.",
        "de": "Die Rohdaten liegen unverändert als Zeilen-JSON und als SQLite-Datenbank vor "
              "und können auf Anforderung vollständig übergeben werden. Die folgenden "
              "Prüfsummen bezeichnen die Dateien, aus denen dieser Bericht erzeugt wurde.",
    },
    "th_file": {"en": "File", "de": "Datei"},
    "th_size": {"en": "Size", "de": "Größe"},
    "th_sha256": {"en": "SHA-256", "de": "SHA-256"},
}


from .findings import FINDING_STRINGS  # noqa: E402

STRINGS.update(FINDING_STRINGS)


class Strings:
    """Language-bound lookup with English fallback."""

    def __init__(self, lang: str = DEFAULT_LANG):
        self.lang = (lang or DEFAULT_LANG).lower()
        if not any(self.lang in entry for entry in STRINGS.values()):
            LOG.warning("no translations for language %r -- falling back to English", self.lang)
            self.lang = DEFAULT_LANG

    def available(self) -> list:
        langs: set = set()
        for entry in STRINGS.values():
            langs.update(entry)
        return sorted(langs)

    def __call__(self, key: str, **kwargs) -> str:
        entry = STRINGS.get(key)
        if entry is None:
            LOG.warning("missing report string: %s", key)
            return key
        text = entry.get(self.lang) or entry.get(DEFAULT_LANG) or key
        if not kwargs:
            return text
        try:
            return text.format(**kwargs)
        except KeyError as exc:
            LOG.warning("string %s is missing placeholder %s", key, exc)
            return text
