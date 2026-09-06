"""Text for the automatic assessment.

Kept apart from the general report strings because there are a lot of them and
they are written differently: each one has to state a conclusion and, in the
same breath, the figures it rests on. A conclusion a reader cannot check is
worth less than none, because an operator will check it.

Merged into the main string table at import.
"""

FINDING_STRINGS: dict = {
    # -- section furniture -------------------------------------------------
    "sa_heading": {"en": "Assessment", "de": "Bewertung"},
    "sa_intro": {
        "en": "The following conclusions are derived automatically from the measurements "
              "in this report. Each states the figures it rests on, so every one of them "
              "can be checked against the tables below.",
        "de": "Die folgenden Schlussfolgerungen wurden automatisch aus den Messwerten "
              "dieses Berichts abgeleitet. Zu jeder sind die zugrunde liegenden Zahlen "
              "angegeben, sodass sich alle anhand der untenstehenden Tabellen "
              "nachprüfen lassen.",
    },
    "sev_critical": {"en": "Finding", "de": "Befund"},
    "sev_warning": {"en": "Caution", "de": "Hinweis"},
    "sev_neutral": {"en": "Observation", "de": "Beobachtung"},
    "sev_good": {"en": "In order", "de": "Unauffällig"},

    # -- integrity ---------------------------------------------------------
    "f_integrity_leaked_title": {
        "en": "These measurements do not all describe the connection under investigation",
        "de": "Diese Messwerte beschreiben nicht durchgehend den geprüften Anschluss",
    },
    "f_integrity_leaked_body": {
        "en": "{leaked} of {graded} verification checks found the probe leaving by {address}, "
              "outside the expected range {expected}, across {windows} period(s). During "
              "those periods the router had moved the probe to another uplink, so the "
              "figures describe that one instead. Correct the router's policy route before "
              "relying on this report.",
        "de": "{leaked} von {graded} Prüfungen stellten fest, dass die Messsonde über "
              "{address} und damit außerhalb des erwarteten Bereichs {expected} nach außen "
              "ging, verteilt auf {windows} Zeitraum/Zeiträume. In diesen Zeiträumen hatte "
              "der Router die Sonde auf einen anderen Anschluss umgeleitet; die Werte "
              "beschreiben dann diesen. Die Routing-Regel ist zu korrigieren, bevor dieser "
              "Bericht verwendet wird.",
    },
    "f_integrity_confirmed_title": {
        "en": "The measurements describe the stated connection",
        "de": "Die Messwerte beschreiben den genannten Anschluss",
    },
    "f_integrity_confirmed_body": {
        "en": "All {confirmed} verification checks confirmed that the probe's own traffic "
              "left by {expected}, as observed by independent external services.",
        "de": "Alle {confirmed} Prüfungen bestätigten, dass der Datenverkehr der Messsonde "
              "über {expected} nach außen ging, festgestellt durch unabhängige externe "
              "Dienste.",
    },
    "f_integrity_unverified_title": {
        "en": "The uplink used was not verified",
        "de": "Der genutzte Anschluss wurde nicht verifiziert",
    },
    "f_integrity_unverified_body": {
        "en": "No egress verification ran during this period, so there is no independent "
              "confirmation that the probe used the connection named here rather than a "
              "backup uplink.",
        "de": "In diesem Zeitraum fand keine Egress-Prüfung statt. Es gibt daher keine "
              "unabhängige Bestätigung, dass die Messsonde den hier genannten Anschluss "
              "genutzt hat und nicht einen Ersatzanschluss.",
    },

    # -- how much data -----------------------------------------------------
    "f_too_little_data_title": {
        "en": "Too little data to draw conclusions",
        "de": "Zu wenig Daten für belastbare Aussagen",
    },
    "f_too_little_data_body": {
        "en": "Only {minutes} measured minutes are available. Treat everything below as "
              "provisional.",
        "de": "Es liegen nur {minutes} Messminuten vor. Alle folgenden Angaben sind als "
              "vorläufig zu betrachten.",
    },
    "f_short_period_title": {
        "en": "Short measurement period",
        "de": "Kurzer Messzeitraum",
    },
    "f_short_period_body": {
        "en": "{minutes} measured minutes ({hours} hours) is less than a full day, so daily "
              "patterns such as an evening peak cannot yet be distinguished from a constant "
              "fault.",
        "de": "{minutes} Messminuten ({hours} Stunden) sind weniger als ein voller Tag. "
              "Tagesmuster wie eine Abendspitze lassen sich daher noch nicht von einem "
              "dauerhaften Fehler unterscheiden.",
    },

    # -- headline loss -----------------------------------------------------
    "f_loss_severe_title": {
        "en": "The connection is severely disrupted",
        "de": "Der Anschluss ist erheblich gestört",
    },
    "f_loss_severe_body": {
        "en": "{loss} of packets were lost across {minutes} measured minutes, with "
              "{blackout} minutes of total outage and {degraded} degraded minutes in "
              "{events} separate events. Loss at this level makes interactive use "
              "unreliable and breaks long-lived connections.",
        "de": "Über {minutes} Messminuten gingen {loss} der Pakete verloren, davon "
              "{blackout} Minuten Totalausfall und {degraded} gestörte Minuten in {events} "
              "separaten Ereignissen. Verluste in dieser Höhe machen interaktive Nutzung "
              "unzuverlässig und brechen länger bestehende Verbindungen ab.",
    },
    "f_loss_degraded_title": {
        "en": "The connection is measurably degraded",
        "de": "Der Anschluss ist messbar beeinträchtigt",
    },
    "f_loss_degraded_body": {
        "en": "{loss} of packets were lost across {minutes} measured minutes, with "
              "{degraded} degraded minutes in {events} events. Loss above one percent is "
              "noticeable in voice and video calls and in interactive sessions.",
        "de": "Über {minutes} Messminuten gingen {loss} der Pakete verloren, mit "
              "{degraded} gestörten Minuten in {events} Ereignissen. Verluste über einem "
              "Prozent sind bei Sprach- und Videoanrufen sowie in interaktiven Sitzungen "
              "spürbar.",
    },
    "f_loss_minor_title": {
        "en": "Minor packet loss",
        "de": "Geringer Paketverlust",
    },
    "f_loss_minor_body": {
        "en": "{loss} of packets were lost across {minutes} measured minutes. This is above "
              "a clean line but below the level at which most applications suffer.",
        "de": "Über {minutes} Messminuten gingen {loss} der Pakete verloren. Das liegt über "
              "dem Wert einer einwandfreien Leitung, aber unter der Schwelle, ab der die "
              "meisten Anwendungen beeinträchtigt werden.",
    },
    "f_loss_clean_title": {
        "en": "No significant packet loss in this period",
        "de": "Kein nennenswerter Paketverlust in diesem Zeitraum",
    },
    "f_loss_clean_body": {
        "en": "{loss} of packets were lost across {minutes} measured minutes. If the fault "
              "is intermittent, a period without it is expected and does not disprove it.",
        "de": "Über {minutes} Messminuten gingen {loss} der Pakete verloren. Bei einer "
              "sporadischen Störung ist ein unauffälliger Zeitraum zu erwarten und "
              "widerlegt die Störung nicht.",
    },

    # -- isolation against the control ------------------------------------
    "f_isolated_to_link_title": {
        "en": "The fault is specific to this connection",
        "de": "Die Störung betrifft gezielt diesen Anschluss",
    },
    "f_isolated_to_link_body": {
        "en": "In {only_bad} of {common} jointly measured minutes only this connection was "
              "disrupted, while {control} was working normally at the same moment "
              "({primary_loss} against {control_loss} loss). In {blackout_fine} minutes "
              "this connection was completely dead while the other was unaffected. Both "
              "links were measured from the same network, with the same hardware and "
              "software, against the same targets, so a cause in the customer network or "
              "in the public internet is excluded.",
        "de": "In {only_bad} von {common} gemeinsam gemessenen Minuten war ausschließlich "
              "dieser Anschluss gestört, während {control} im selben Moment einwandfrei "
              "arbeitete ({primary_loss} gegenüber {control_loss} Verlust). In "
              "{blackout_fine} Minuten war dieser Anschluss vollständig tot, der andere "
              "unbeeinträchtigt. Beide Leitungen wurden aus demselben Netz, mit derselben "
              "Hard- und Software und gegen dieselben Ziele gemessen; eine Ursache im "
              "Kundennetz oder im öffentlichen Internet ist damit ausgeschlossen.",
    },
    "f_both_links_bad_title": {
        "en": "Both connections were disrupted at the same times",
        "de": "Beide Anschlüsse waren zu denselben Zeiten gestört",
    },
    "f_both_links_bad_body": {
        "en": "{both} of {common} jointly measured minutes were disrupted on both links at "
              "once. A common cause — the customer network, the measurement itself, or a "
              "shared path — cannot be excluded from these figures alone.",
        "de": "{both} von {common} gemeinsam gemessenen Minuten waren auf beiden Leitungen "
              "gleichzeitig gestört. Eine gemeinsame Ursache — Kundennetz, Messaufbau oder "
              "ein gemeinsamer Pfad — lässt sich allein aus diesen Zahlen nicht "
              "ausschließen.",
    },
    "f_control_worse_title": {
        "en": "The reference link was the worse of the two",
        "de": "Die Referenzleitung war die schlechtere von beiden",
    },
    "f_control_worse_body": {
        "en": "{control_only} of {common} jointly measured minutes were disrupted only on "
              "{control}, against {only_bad} only on the connection under investigation. "
              "This period does not support a complaint about the latter.",
        "de": "{control_only} von {common} gemeinsam gemessenen Minuten waren ausschließlich "
              "auf {control} gestört, gegenüber {only_bad} ausschließlich auf dem geprüften "
              "Anschluss. Dieser Zeitraum stützt keine Beanstandung des geprüften "
              "Anschlusses.",
    },
    "f_no_isolation_signal_title": {
        "en": "No clear difference between the two connections",
        "de": "Kein deutlicher Unterschied zwischen den Anschlüssen",
    },
    "f_no_isolation_signal_body": {
        "en": "Across {common} jointly measured minutes, {only_bad} were disrupted only on "
              "this connection and {control_only} only on {control}. Neither figure is "
              "large enough to isolate a fault to one link.",
        "de": "Über {common} gemeinsam gemessene Minuten waren {only_bad} ausschließlich auf "
              "diesem Anschluss gestört und {control_only} ausschließlich auf {control}. "
              "Keiner der Werte genügt, um eine Störung einer Leitung zuzuordnen.",
    },
    "f_no_control_title": {
        "en": "No reference link, so the fault cannot be isolated",
        "de": "Keine Referenzleitung, Störung nicht eingrenzbar",
    },
    "f_no_control_body": {
        "en": "Without a second connection measured in parallel, these figures cannot "
              "distinguish a fault on this link from one in the customer network or the "
              "wider internet. A control link is the single most effective addition to this "
              "evidence.",
        "de": "Ohne einen parallel gemessenen zweiten Anschluss lässt sich anhand dieser "
              "Zahlen nicht unterscheiden, ob die Störung auf dieser Leitung, im Kundennetz "
              "oder im übrigen Internet liegt. Eine Referenzleitung ist die wirksamste "
              "Ergänzung dieser Beweisführung.",
    },

    # -- where the loss is -------------------------------------------------
    "f_operator_network_loss_title": {
        "en": "The loss occurs inside the operator's own network",
        "de": "Der Verlust tritt im Netz des Anbieters selbst auf",
    },
    "f_operator_network_loss_body": {
        "en": "{loss} of packets were lost against the operator's own first network node "
              "({hops}) — inside their network, before any handover to third parties. Loss "
              "measured at this point cannot be attributed to the public internet, to the "
              "second uplink, or to the customer network.",
        "de": "Gegen den ersten Netzknoten des Anbieters selbst ({hops}) gingen {loss} der "
              "Pakete verloren — innerhalb seines Netzes, vor jeder Übergabe an Dritte. An "
              "dieser Stelle gemessener Verlust kann weder dem öffentlichen Internet noch "
              "dem zweiten Anschluss noch dem Kundennetz zugerechnet werden.",
    },
    "f_beyond_first_hop_title": {
        "en": "The operator's first node itself is not losing packets",
        "de": "Der erste Netzknoten des Anbieters verliert selbst keine Pakete",
    },
    "f_beyond_first_hop_body": {
        "en": "Loss against the operator's first node ({hops}) was only {loss}, so the "
              "impairment lies beyond it rather than on the access line itself.",
        "de": "Gegen den ersten Netzknoten des Anbieters ({hops}) betrug der Verlust nur "
              "{loss}. Die Beeinträchtigung liegt damit dahinter und nicht auf dem "
              "Anschluss selbst.",
    },

    # -- shape over the day ------------------------------------------------
    "f_congestion_pattern_title": {
        "en": "The pattern points to congestion, not a hardware fault",
        "de": "Das Muster deutet auf Überlastung, nicht auf einen Hardwarefehler",
    },
    "f_congestion_pattern_body": {
        "en": "Loss averaged {peak} during the evening peak (18:00–24:00) against {rest} "
              "over the rest of the day. Loss that concentrates in the busy hours is "
              "characteristic of insufficient capacity on the segment rather than a faulty "
              "line or device.",
        "de": "Der Verlust betrug in der Abendspitze (18:00–24:00) im Mittel {peak} "
              "gegenüber {rest} in der übrigen Zeit. Ein Verlust, der sich auf die "
              "Hauptverkehrszeit konzentriert, ist typisch für unzureichende Kapazität im "
              "Segment und nicht für eine defekte Leitung oder ein defektes Gerät.",
    },
    "f_constant_pattern_title": {
        "en": "The pattern points to a fault, not to congestion",
        "de": "Das Muster deutet auf einen Defekt, nicht auf Überlastung",
    },
    "f_constant_pattern_body": {
        "en": "Loss averaged {peak} during the evening peak against {rest} over the rest of "
              "the day — essentially unchanged. Congestion would concentrate in the busy "
              "hours; loss spread evenly across the day is characteristic of a physical or "
              "equipment fault.",
        "de": "Der Verlust betrug in der Abendspitze im Mittel {peak} gegenüber {rest} in "
              "der übrigen Zeit — im Wesentlichen unverändert. Überlastung würde sich auf "
              "die Hauptverkehrszeit konzentrieren; ein gleichmäßig über den Tag verteilter "
              "Verlust ist typisch für einen physikalischen oder Gerätefehler.",
    },

    # -- address family ----------------------------------------------------
    "f_conclusions_withheld_title": {
        "en": "No conclusions are drawn about this connection for this period",
        "de": "Für diesen Zeitraum werden keine Aussagen zu diesem Anschluss getroffen",
    },
    "f_conclusions_withheld_body": {
        "en": "Only {confirmed} of the verification checks confirmed that the probe used "
              "the connection named here, so for most of this period the measurements "
              "describe a different uplink. Drawing conclusions from them would be "
              "misleading, and they are therefore withheld. Correct the router's policy "
              "route so the probe cannot fail over, then measure again.",
        "de": "Nur {confirmed} der Prüfungen bestätigten, dass die Messsonde den hier "
              "genannten Anschluss genutzt hat; für den überwiegenden Teil des Zeitraums "
              "beschreiben die Messwerte daher einen anderen Anschluss. Daraus Aussagen "
              "abzuleiten wäre irreführend, weshalb darauf verzichtet wird. Die "
              "Routing-Regel ist so zu korrigieren, dass die Sonde nicht ausweichen kann; "
              "anschließend ist erneut zu messen.",
    },
    "f_family_broken_title": {
        "en": "{family} is unusable, which breaks sites that ping perfectly",
        "de": "{family} ist unbrauchbar, wodurch Seiten ausfallen, die im Ping einwandfrei sind",
    },
    "f_family_broken_body": {
        "en": "{count} of the sites tested could not be reached over {family} while "
              "{working} worked normally: {hosts}. {example} resolves to {address} over "
              "{family}, and {fail} of connection attempts to it over {family} failed. A "
              "browser tries the broken family first, so such sites fail to load entirely "
              "— even though packet loss measurements over {working} stay clean. This is a "
              "distinct fault from packet loss and is invisible to ping.",
        "de": "{count} der geprüften Websites waren über {family} nicht erreichbar, während "
              "{working} einwandfrei funktionierte: {hosts}. {example} löst über {family} "
              "auf {address} auf; {fail} der Verbindungsversuche dorthin über {family} "
              "schlugen fehl. Ein Browser versucht zuerst die defekte Adressfamilie, sodass "
              "solche Seiten vollständig ausfallen — obwohl Paketverlustmessungen über "
              "{working} unauffällig bleiben. Das ist ein von Paketverlust getrennter "
              "Fehler und im Ping nicht sichtbar.",
    },

    # -- DNS ---------------------------------------------------------------
    "f_resolver_fault_title": {
        "en": "The operator's name servers are at fault, not the line",
        "de": "Die Nameserver des Anbieters sind ursächlich, nicht die Leitung",
    },
    "f_resolver_fault_body": {
        "en": "{isp} of queries to the operator's own resolvers failed, against {public} to "
              "public resolvers reached over the same connection in the same period. The "
              "line carried the queries; the operator's resolvers did not answer them.",
        "de": "{isp} der Abfragen an die Resolver des Anbieters schlugen fehl, gegenüber "
              "{public} an öffentliche Resolver, die über denselben Anschluss im selben "
              "Zeitraum erreicht wurden. Die Leitung hat die Abfragen transportiert; die "
              "Resolver des Anbieters haben sie nicht beantwortet.",
    },
    "f_dns_both_bad_title": {
        "en": "Name resolution failed on all resolvers",
        "de": "Namensauflösung schlug bei allen Resolvern fehl",
    },
    "f_dns_both_bad_body": {
        "en": "{isp} of queries to the operator's resolvers and {public} to public resolvers "
              "failed. Failures on both point to the connection carrying the queries rather "
              "than to the resolvers themselves.",
        "de": "{isp} der Abfragen an die Resolver des Anbieters und {public} an öffentliche "
              "Resolver schlugen fehl. Fehler bei beiden deuten auf den Transport über den "
              "Anschluss hin und nicht auf die Resolver selbst.",
    },

    # -- nightly restart ---------------------------------------------------
    "f_restart_harmful_title": {
        "en": "The nightly restart is followed by the worst hours of the day",
        "de": "Auf den nächtlichen Neustart folgen die schlechtesten Stunden des Tages",
    },
    "f_restart_harmful_body": {
        "en": "Loss averaged {after} in the twelve hours after the {device} restart against "
              "{later} in the twelve hours that follow. The restart is not curing the fault; "
              "the instability follows it. Stopping the restart is the next thing to test.",
        "de": "In den zwölf Stunden nach dem Neustart des {device} betrug der Verlust im "
              "Mittel {after} gegenüber {later} in den darauffolgenden zwölf Stunden. Der "
              "Neustart behebt die Störung nicht; die Instabilität folgt ihm. Als nächstes "
              "sollte geprüft werden, ob ein Verzicht auf den Neustart hilft.",
    },
    "f_restart_helpful_title": {
        "en": "The connection degrades the longer the device runs",
        "de": "Der Anschluss verschlechtert sich, je länger das Gerät läuft",
    },
    "f_restart_helpful_body": {
        "en": "Loss averaged {after} in the twelve hours after the {device} restart against "
              "{later} later in the cycle. Degradation that accumulates with uptime and "
              "clears on restart is characteristic of a fault in the device itself, which "
              "supports asking for it to be replaced.",
        "de": "In den zwölf Stunden nach dem Neustart des {device} betrug der Verlust im "
              "Mittel {after} gegenüber {later} im weiteren Verlauf. Eine mit der Laufzeit "
              "zunehmende und durch Neustart behobene Verschlechterung ist typisch für einen "
              "Fehler im Gerät selbst und stützt die Forderung nach dessen Austausch.",
    },
}
