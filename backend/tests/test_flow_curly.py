"""Flow order for Dart, JavaScript and TypeScript (D32): read by patterns, the same flow, critical path and advice as
Python's (D25, D27). Nothing is run or sent."""

import textwrap
from pathlib import Path

from flowforge.flow import flow_of

SUPABASE = """
    import 'package:supabase_flutter/supabase_flutter.dart';

    SupabaseClient get supabaseClient => Supabase.instance.client;
"""
TRIPS = """
    import 'supabase_service.dart';

    /// Null if the trip doesn't exist.
    Future<Trip?> getTrip(String tripId) async {
      final row = await supabaseClient.from('trips').select().eq('id', tripId).maybeSingle();
      return row == null ? null : Trip.fromJson(row);
    }

    Future<List<Item>> getItineraryItems(String tripId) async {
      final rows = await supabaseClient
          .from('itinerary_items')
          .select()
          .eq('trip_id', tripId);
      return rows.map(Item.fromJson).toList();
    }
"""
ROUTES = """
    import 'package:http/http.dart' as http;

    Future<String> getRoute(List<Item> stops) async {
      final coords = stops.map((s) => '${s.lon},${s.lat}').join(';');
      final response = await http.get(Uri.parse('https://router.project-osrm.org/route/v1/driving/$coords'));
      return response.body;
    }
"""
OFFLINE = """
    import 'trip_service.dart';
    import 'routing.dart';

    Future<void> downloadTrip(String tripId) async {
      final trip = await getTrip(tripId);
      if (trip == null) throw StateError('Trip $tripId not found');
      final items = await getItineraryItems(tripId);
      final route = await getRoute(items);
      save(trip, items, route);
    }

    Future<void> refresh(String id) async {
      final trip = await getTrip(id);
      final items = await getItineraryItems(id);
      show(trip, items);
    }
"""


def write(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return root


def edges(flow) -> set[tuple[str, str, str | None]]:
    return {(e.source, e.target, e.when) for e in flow.edges}


def dart_app(tmp_path: Path) -> Path:
    return write(tmp_path / "app", {"lib/services/supabase_service.dart": SUPABASE, "lib/services/trip_service.dart": TRIPS,
                                    "lib/services/routing.dart": ROUTES, "lib/services/offline.dart": OFFLINE})


def test_a_flutter_style_dart_app_gets_its_flow_from_the_code(tmp_path):
    flow = flow_of(dart_app(tmp_path)).flow
    assert flow.patterns == ["dart"]
    by_id = {n.id: n for n in flow.nodes}
    # downloadTrip: get the trip, stop if it isn't there, then the stops, then the route
    assert by_id["start-downloadTrip"].evidence[0].ref == "lib/services/offline.dart:4"
    assert by_id["api-supabase-1"].what == "get trip" and by_id["api-supabase-1"].evidence[0].ref == "lib/services/offline.dart:5"
    assert by_id["if-1"].title == 'Did "get trip" fail?'
    assert by_id["api-supabase-2"].what == "get itinerary items"
    assert by_id["api-osrm-1"].what == "get route"
    assert {("start-downloadTrip", "api-supabase-1", None), ("api-supabase-1", "if-1", None), ("if-1", "stop-1", "yes"),
            ("if-1", "api-supabase-2", "no"), ("api-supabase-2", "api-osrm-1", None)} <= edges(flow)


def test_a_call_after_an_early_stop_waits_for_the_check_so_it_gets_no_advice(tmp_path):
    flow = flow_of(dart_app(tmp_path)).flow
    # "get itinerary items" comes after `if (trip == null) throw`: D25 groups calls that could start at the same
    # moment, and this one waits for the check (whether advice should reach across a check is open question 7)
    assert not any("api-supabase-2" in a.nodes for a in flow.advice)


def test_two_dart_awaits_in_a_row_get_the_record_wait_written_out(tmp_path):
    flow = flow_of(dart_app(tmp_path)).flow
    advice = next(a for a in flow.advice if set(a.nodes) == {"api-supabase-3", "api-supabase-4"})
    change = advice.change
    assert change.path == "lib/services/offline.dart" and change.first_line == 13
    assert change.before == ["  final trip = await getTrip(id);", "  final items = await getItineraryItems(id);"]
    assert change.after == ["  final (trip, items) = await (getTrip(id), getItineraryItems(id)).wait;"]
    assert change.import_text == "import 'dart:async';"


TS_API = """
    export async function getWeather(city: string) {
      const res = await fetch(`https://api.open-meteo.com/v1/forecast?city=${city}`);
      return res.json();
    }

    export async function getPlace(city: string) {
      const res = await fetch("https://nominatim.openstreetmap.org/search?q=" + city);
      return res.json();
    }
"""
TS_PLAN = """
    import { getWeather, getPlace } from "./api";

    export async function plan(city: string) {
      const weather = await getWeather(city);
      const place = await getPlace(city);
      // await getPlace(city) { in a comment
      const note = "await getPlace(city) {";
      return { weather, place, note };
    }

    export const planFast = async (city: string) => {
      const [weather, place] = await Promise.all([getWeather(city), getPlace(city)]);
      return { weather, place };
    };
"""


def test_typescript_awaits_get_promise_all_and_strings_or_comments_change_nothing(tmp_path):
    flow = flow_of(write(tmp_path / "web", {"src/api.ts": TS_API, "src/plan.ts": TS_PLAN})).flow
    assert flow.patterns == ["typescript"]
    starts = sorted(n.id for n in flow.nodes if n.kind == "start")
    assert starts == ["start-plan", "start-planFast"]
    (advice,) = flow.advice   # planFast already runs both together
    assert set(advice.nodes) == {"api-open-meteo-1", "api-nominatim-1"}
    assert advice.change.after == ["  const [weather, place] = await Promise.all([getWeather(city), getPlace(city)]);"]
    assert advice.change.import_text is None
    gathered = {e.target for e in flow.edges if e.source == "start-planFast"}
    assert gathered == {"api-open-meteo-2", "api-nominatim-2"}


def test_javascript_without_semicolons_still_splits_statements(tmp_path):
    repo = write(tmp_path / "js", {"api.js": TS_API.replace(": string", ""), "main.js": """
        const { getWeather, getPlace } = require("./api")

        async function main() {
          const a = await getWeather("Paris")
          const b = await getPlace("Paris")
          return [a, b]
        }
    """})
    flow = flow_of(repo).flow
    (advice,) = flow.advice
    assert advice.change.after == ['  const [a, b] = await Promise.all([getWeather("Paris"), getPlace("Paris")])']


def test_a_typed_typescript_declaration_is_left_to_move_by_hand(tmp_path):
    repo = write(tmp_path / "web", {"src/api.ts": TS_API, "src/plan.ts": """
        import { getWeather, getPlace } from "./api";

        export async function plan(city: string) {
          const weather: Weather = await getWeather(city);
          const place = await getPlace(city);
          return { weather, place };
        }
    """})
    (advice,) = flow_of(repo).flow.advice
    assert advice.change is None and "line 4" in advice.prompt


def test_a_repo_with_python_and_dart_shows_both(tmp_path):
    repo = dart_app(tmp_path)
    write(repo, {"tools/report.py": """
        import httpx

        def report():
            return httpx.get("https://api.weather.test/v1/today")
    """})
    flow = flow_of(repo).flow
    assert flow.patterns == ["dart"]
    assert {"start-report", "start-downloadTrip"} <= {n.id for n in flow.nodes if n.kind == "start"}


def test_no_code_the_flow_can_read_says_so(tmp_path):
    result = flow_of(write(tmp_path / "x", {"README.md": "nothing here\n", "data.json": "{}\n"}))
    assert result.flow is None and result.message == "Flow order reads Python, Dart, JavaScript and TypeScript."


PROVIDER = """
    import 'package:flutter/widgets.dart';
    import '../services/supabase_service.dart';
    import '../services/trip_service.dart';

    class TripsProvider {
      List<Trip> _trips = [];

      Future<void> loadTrips(String userId) async {
        _trips = await supabaseClient.from('trips').select().eq('user_id', userId);
      }

      Future<void> openTrip(Trip trip) async {
        await getItineraryItems(trip.id);
      }

      Future<void> openNext(String userId) async {
        await loadTrips(userId);
        final trip = _trips.first;
        await openTrip(trip);
      }

      Future<void> signIn(String email, String password) async {
        await supabaseClient.auth.signInWithPassword(email: email, password: password);
        await supabaseClient.from('profiles').insert({'email': email});
      }

      Widget build(BuildContext context) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          getTrip('a');
        });
        return Button(onTap: () async => await getItineraryItems('b'));
      }
    }
"""


def test_hidden_order_through_fields_auth_and_callbacks_gives_no_wrong_advice(tmp_path):
    repo = dart_app(tmp_path)
    write(repo, {"lib/features/trips_provider.dart": PROVIDER})
    flow = flow_of(repo).flow
    provider = [a for a in flow.advice if any(r.startswith("lib/features/") for r in a.refs)]
    # openNext: loadTrips fills _trips, which the next line reads; signIn: the profile needs the session;
    # build: the callbacks run later, not now
    assert provider == []
    starts = {n.title for n in flow.nodes if n.kind == "start"}
    assert "TripsProvider.build()" not in starts and "TripsProvider.openNext()" in starts


def test_a_call_that_reads_then_writes_one_service_counts_as_a_write(tmp_path):
    repo = dart_app(tmp_path)
    write(repo, {"lib/features/accounts.dart": """
        import '../services/supabase_service.dart';

        Future<void> makeProfileIfMissing(String id) async {
          final found = await supabaseClient.from('profiles').select().eq('id', id).maybeSingle();
          if (found == null) await supabaseClient.from('profiles').insert({'id': id});
        }

        Future<void> signIn(String email, String password, String id) async {
          await supabaseClient.auth.signInWithPassword(email: email, password: password);
          await makeProfileIfMissing(id);
        }
    """})
    flow = flow_of(repo).flow
    assert not [a for a in flow.advice if any(r.startswith("lib/features/") for r in a.refs)]


def test_as_written_is_the_slowest_entry_point_not_every_entry_added_up(tmp_path):
    flow = flow_of(dart_app(tmp_path)).flow
    # downloadTrip runs 3 calls one after another (900 ms); refresh runs 2 (600 ms): separate actions, never summed
    assert flow.written_ms == 900


def test_a_check_that_only_stops_on_ui_state_is_not_drawn_but_a_check_on_a_result_is(tmp_path):
    repo = dart_app(tmp_path)
    write(repo, {"lib/features/budget_screen.dart": """
        import '../services/trip_service.dart';

        class BudgetScreenState {
          int _request = 0;

          Future<void> load(String id) async {
            final request = ++_request;
            final items = await getItineraryItems(id);
            if (!mounted || request != _request) return;
            show(items);
          }
        }
    """})
    flow = flow_of(repo).flow
    questions = {n.title for n in flow.nodes if n.kind == "decision"}
    assert 'Did "get trip" fail?' in questions   # downloadTrip's check reads a call's result: kept
    assert not any("mounted" in (n.condition or "") for n in flow.nodes)


def test_each_action_has_its_own_times_slowest_first(tmp_path):
    flow = flow_of(dart_app(tmp_path)).flow
    actions = [(a.title, a.written_ms, a.could_ms, a.calls) for a in flow.actions]
    assert actions == [("downloadTrip()", 900.0, 900.0, 3), ("refresh()", 600.0, 300.0, 2)]
    assert flow.actions[0].path[0] == "start-downloadTrip"
