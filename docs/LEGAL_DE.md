QuantPy - Rechtliche Hinweise und Betreiber-Leitfaden
Dokumentversion: 2026-11   (muss zu LEGAL_DOC_VERSION in quantpy/risk/compliance.py passen)
WICHTIG: Dies ist eine technische Orientierungshilfe, KEINE Rechtsberatung und
KEINE Steuerberatung. Rechtsstand und Auslegung ändern sich. Vor jedem Betrieb
mit echtem Geld, mit Geld Dritter oder im Rahmen eines Unternehmens (z. B.
einer GmbH) lässt du den konkreten Fall von einer Rechtsanwältin/einem
Rechtsanwalt bzw. einer Steuerberaterin/einem Steuerberater prüfen.

Was QuantPy ist - und was nicht
---
QuantPy ist Forschungs- und Lernsoftware für Backtests und Papierhandel
QuantPy ist keine Anlageberatung, keine Anlageempfehlung, keine
Finanzportfolioverwaltung, keine Anlagevermittlung und kein Angebot von
Finanzinstrumenten. Die Ausgaben der KI sind Rechenergebnisse, keine
persönlichen Empfehlungen.
QuantPy darf NICHT mit Geld Dritter betrieben werden. Wer fremdes Geld nach
einer Strategie anlegt oder Empfehlungen an andere gibt, erbringt
erlaubnispflichtige Finanzdienstleistungen (KWG/WpIG, § 2 Abs. 8 WpHG) und
braucht vorher eine Erlaubnis der BaFin.
Es gibt keine Erfolgs- oder Gewinngarantie. Handel mit Wertpapieren kann zum
Totalverlust des eingesetzten Kapitals führen.

Einschlägige Regelwerke und wie QuantPy sie technisch berücksichtigt
---
Regelwerk / Thema	Technische Umsetzung in QuantPy
Algorithmischer Handel: MiFID II Art. 17, § 80 Abs. 2/3 WpHG, Del. VO (EU) 2017/589 (RTS 6): Systeme und Risikokontrollen, Tests, Notausschalter	Vorab-Risikoprüfung jeder Order (RiskEngine.pre_trade), harte Limits (RiskLimits), persistenter Kill-Switch, Order-Obergrenzen, Mindestabstände, Papierhandel als Standard
Kennzeichnung algorithmischer Aufträge	Jede Order trägt die Client-Order-ID "QPY-ALGO-..."
Erlaubnis für Eigenhandel/Hochfrequenzhandel (KWG, WpIG)	Aktivitätslimits (max. Orders/Stunde und Tag, Mindestabstand je Symbol, Zyklus >= 60 s). QuantPy ist nicht für Hochfrequenzhandel gebaut
Marktmissbrauch: MAR (VO (EU) 596/2014) Art. 12/15 (Marktmanipulation), Art. 8/14 (Insiderhandel)	Wash-Trade-/Churn-Schutz (Wiedereinstiegssperre nach Verkauf), Fat-Finger-Prüfung, Liquiditätsfilter (keine Penny Stocks), Sperrliste `restricted_symbols.txt` für Titel, bei denen du Insiderinformationen hast oder Beschränkungen unterliegst
Leerverkaufsverordnung (VO (EU) 236/2012)	Short-Selling technisch ausgeschlossen (Verkauf nur bis zur Höhe der Long-Position)
Komplexe/gehebelte Produkte (Produktinformationspflichten, PRIIPs)	Gehebelte/inverse/Volatilitäts-ETPs standardmäßig gesperrt; Hebel (Leverage) technisch nicht möglich
Dokumentation / Nachvollziehbarkeit	Manipulationssicheres Audit-Log (Hash-Kette) für jede KI-Entscheidung, Risikoentscheidung, Order, Anmeldung und Kill-Switch-Aktion
Aufsichtsrechtlicher Betrieb (DORA, VO (EU) 2022/2554; MaRisk), falls QuantPy im Umfeld eines beaufsichtigten Unternehmens läuft	Nicht abgedeckt - dort sind eigene IKT-Risiko-, Auslagerungs- und Meldeprozesse nötig
Datenschutz (DSGVO Art. 5, 6, 25, 32)	Datensparsamkeit: Audit-Log enthält Benutzername und IP nur für Login-Ereignisse; 2FA, Lockout, lokale Bindung (127.0.0.1)
KI-Verordnung (VO (EU) 2024/1689)	KI wird nur beratend genutzt (Human-/Rule-in-the-loop), Entscheidungen sind protokolliert; Betreiber-Pflicht zur KI-Kompetenz (Art. 4) liegt bei dir. Einstufung als nicht Hochrisiko nach derzeitiger Einschätzung, aber prüfen lassen
Irreführende Werbung (UWG)	README und Website enthalten bewusst keine Rendite- oder Performanceversprechen. Das gilt auch für deine eigenen Veröffentlichungen

Wann du ohne Erlaubnis handeln darfst - und wann nicht (Orientierung)
---
Eigenes Geld, eigenes Depot, privat, Papierhandel: unkritisch, solange du
keine Dritten einbindest.
Eigenes Geld im Echtgeldbetrieb: Ob und welche Pflichten aus dem
algorithmischen Handel entstehen (z. B. Anzeige/Erlaubnis bei
Hochfrequenzhandel, § 80 Abs. 2 WpHG), hängt von Umfang, Geschwindigkeit,
Handelsplatz und Rechtsform ab. Bei den in QuantPy voreingestellten
Zeitabständen (Minuten) und Limits ist Hochfrequenzhandel nicht beabsichtigt;
eine verbindliche Einordnung muss aber ein Rechtsberater vornehmen.
Handel über eine Gesellschaft (z. B. GmbH): zusätzliche Fragen zu
Gewerbe-/Aufsichtsrecht, Buchführung, Körperschaft- und Gewerbesteuer.
Broker: Prüfe, ob dein Broker für deinen Wohnsitz Konten und API-Handel
anbietet und was seine Geschäftsbedingungen zu automatisiertem Handel,
Marktdatennutzung und Weitergabe sagen. Marktdaten (z. B. IEX-Feed) dürfen
in der Regel nicht weiterverbreitet werden - das Dashboard ist nur privat.
Wenn du Mitarbeiter eines Kredit- oder Finanzdienstleistungsinstituts bist
oder Insiderinformationen haben könntest: interne Regeln zu
Mitarbeitergeschäften beachten und betroffene Titel in
`restricted_symbols.txt` eintragen.

Steuern und Aufbewahrung (Orientierung)
---
Gewinne/Verluste aus Wertpapiergeschäften sind in Deutschland in der Regel
Einkünfte aus Kapitalvermögen (§ 20 EStG). Bei Auslandsdepots ohne
inländischen Steuerabzug musst du sie selbst erklären (Anlage KAP).
Verlustverrechnungsbeschränkungen (z. B. für Aktien) sind zu beachten.
Bei sehr hoher Handelsintensität kann die Einordnung als gewerblich
infrage kommen; bei Handel über eine GmbH gelten Unternehmenssteuern und
Buchführungspflichten.
QuantPy ersetzt keine Depotauszüge und keine Steuerbescheinigungen. Das
Audit-Log ist ein technischer Nachweis. Aufbewahrungsfristen (z. B.
§ 147 AO, § 257 HGB) und Löschpflichten (DSGVO) musst du für deinen Fall
abstimmen. Sichere `audit/` regelmäßig und exportiere es über das Dashboard.

Lizenz und Dritt-Software
---
QuantPy steht unter der BSD-3-Clause-Lizenz (siehe LICENSE). Bei
Weitergabe müssen Copyright-Hinweise erhalten bleiben. Das Projekt geht auf
ein früheres Open-Source-Projekt "QuantPy" zurück (Verweis in der
Dokumentation auf github.com/jsmidt/QuantPy); dessen Urheberrechtshinweis
darf nicht entfernt werden. Bitte kläre die Rechtekette vor einer
Veröffentlichung.
Der Event-Profiler ist konzeptionell von QSTK inspiriert; Quellcode wurde
laut Kommentar nicht übernommen.
Nutze nur deine eigenen API-Schlüssel (Anthropic, Alpaca) und gib sie nie
weiter. Beachte die jeweiligen Nutzungsbedingungen.

Checkliste vor Echtgeld-Betrieb
---
Wochen/Monate im Papierhandel getestet, Ergebnisse und Fehler ausgewertet.
Rechts- und Steuerberatung für deinen Fall eingeholt (Rechtsform, Broker,
Aufsichtsrecht, Steuern).
Broker-Bedingungen gelesen (API-Handel, Marktdaten, Haftung).
`restricted_symbols.txt` gepflegt (Insider-/Interessenkonflikte).
Limits in `.env` bewusst gesetzt (RISK_*), nur Beträge, deren Totalverlust
du verkraftest.
Kill-Switch und Wiederfreigabe (2FA) getestet.
Audit-Log-Sicherung und Aufbewahrungskonzept vorhanden.
Alle drei Freigaben gesetzt: RISK_ALLOW_LIVE_TRADING=true,
QUANTPY_LIVE_CONFIRM=YES_USE_REAL_MONEY und LEGAL_ACK=<Phrase aus
quantpy/risk/compliance.py>.
Zugang abgesichert (TLS/VPN, starke Passwörter, 2FA), Schlüssel rotiert.
Überwachung: du schaust regelmäßig auf das Dashboard; QuantPy ersetzt
keine Aufsicht durch dich.

Grenzen
---
QuantPy kann Rechtskonformität nicht herstellen, sondern nur typische
Risiken technisch begrenzen. Nicht abgedeckt sind u. a.: individuelle
Erlaubnis-/Meldepflichten, Steuererklärung, Geldwäsche-/KYC-Pflichten,
Auslagerungs- und IKT-Pflichten beaufsichtigter Unternehmen, Verbraucher-
und Werberecht deiner eigenen Veröffentlichungen. Maßgeblich sind die
jeweils aktuellen Gesetzestexte und Hinweise von BaFin, ESMA und
Finanzverwaltung.
