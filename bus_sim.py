import csv
import math
import os
import random
import pygame

pygame.init()

# --- Window: the map view on the left, info panel on the right ---
MAP_WIDTH = 1000
PANEL_WIDTH = 210
WIDTH, HEIGHT = MAP_WIDTH + PANEL_WIDTH, 720
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Osh Bus Simulator")
clock = pygame.time.Clock()

# --- The world is much bigger than the window. The camera shows one part of it. ---
WORLD_WIDTH, WORLD_HEIGHT = 3000, 2000
MIN_ZOOM = max(MAP_WIDTH / WORLD_WIDTH, HEIGHT / WORLD_HEIGHT)
MAX_ZOOM = 1.5
SCROLL_SPEED = 12   # pixels per frame when using the arrow keys
KEY_ZOOM = 1.02     # zoom step per frame when holding + / - (or Q / E)

HERE = os.path.dirname(os.path.abspath(__file__))   # stats files are saved next to this script

_font_cache = {}


def get_font(size):
    """Fonts in any size, made once and remembered (making fonts is slow)."""
    size = max(6, int(size))
    if size not in _font_cache:
        _font_cache[size] = pygame.font.SysFont("arial", size, bold=True)
    return _font_cache[size]


# --- Colors ---
GRASS = (0, 128, 0)
ROAD = (49, 49, 49)
CENTER_LINE = (95, 95, 95)
RIVER = (30, 90, 200)
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (128, 128, 128)
SIGN = (218, 165, 32)
SIGN_CROWDED = (255, 99, 71)
TERMINAL_SIGN = (30, 30, 30)
CRIMSON = (220, 20, 60)
MARKET_COLOR = (185, 185, 0)
PANEL_BG = (25, 25, 25)
NIGHT_COLOR = (5, 10, 40)
LIGHT_COLORS = {"green": (40, 220, 60), "yellow": (255, 200, 0), "red": (220, 30, 30),
                "off": (110, 110, 110)}

FPS = 60

# --- Simulation settings (play with these!) ---
BASE_DWELL = 1.0          # seconds at a stop even if nobody gets on/off
SECONDS_PER_PERSON = 0.2  # extra seconds per person getting on or off
CROWDED = 12              # sign turns red at this many waiting
SAFE_GAP = 70             # buses keep at least this far behind the bus in front
ROAD_WIDTH = 46
LANE_OFFSET = 11          # buses drive on the right side of the road
START_HOUR = 6            # the day starts at 06:00
GREEN_TIME = 5.0          # seconds a traffic light stays green for one direction
YELLOW_TIME = 1.5         # seconds of yellow before it turns red
STOP_LINE = 40            # buses stop this far before the middle of a crossing
TRANSFER_PENALTY = 3      # a transfer "feels like" this many extra stops when planning a trip
FARE = 20                 # som each rider pays every time they board
RUNNING_COST = 8          # som per minute for a bus on the road (fuel + driver)
IDLE_COST = 1             # som per minute for a bus waiting in a terminal lot
BREAKDOWNS_PER_HOUR = 0.02  # chance a driving bus breaks down in one hour of driving
GIVE_UP_MINUTES = 90      # people who wait longer than this give up (taxi, walk, stay home)
REPAIR_MINUTES = 30       # how long a repair takes
SPEEDS = [1, 2, 5, 10]    # keys 1-4 pick one; Space pauses
# Time scale: 1 real second = 1 simulated minute (at 1x speed)


def demand_multiplier(hour):
    """How busy the city is at a given hour."""
    if 7 <= hour < 9 or 17 <= hour < 19:
        return 2.5   # rush hour
    if hour >= 22 or hour < 6:
        return 0.2   # night
    return 1.0


def darkness(hour):
    """0 = full daylight, 0.6 = deep night. Smooth dusk and dawn."""
    if 7 <= hour < 18:
        return 0.0
    if 18 <= hour < 21:
        return 0.6 * (hour - 18) / 3        # dusk
    if 5 <= hour < 7:
        return 0.6 * (7 - hour) / 2         # dawn
    return 0.6


# --- Helpers for streets made of straight horizontal / vertical pieces ---
def sign(value):
    return (value > 0) - (value < 0)


def on_segment(p, a, b):
    """Is point p on the straight street from a to b?"""
    if a[0] == b[0] == p[0]:
        return min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
    if a[1] == b[1] == p[1]:
        return min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
    return False


def distance_along(path, point):
    """How far along a line's path a point is (used to put stops in driving order)."""
    total = 0
    for a, b in zip(path, path[1:]):
        if on_segment(point, a, b):
            return total + math.hypot(point[0] - a[0], point[1] - a[1])
        total += math.hypot(b[0] - a[0], b[1] - a[1])
    raise ValueError(f"{point} is not on this line's road")


# --- The Ak-Buura river runs north to south through the city ---
RIVER_PATH = [(1100, 0), (1080, 400), (1120, 800), (1100, 1200), (1150, 1600), (1120, 2000)]

# --- Lines: terminal -> ... -> terminal, then back ---
PATH_53 = [(150, 1850), (600, 1850), (600, 1400), (1000, 1400), (1000, 1000),
           (1900, 1000), (1900, 600), (2400, 600), (2400, 200), (2850, 200)]
PATH_43 = [(1300, 60), (1300, 650), (1200, 650), (1200, 1000),
           (1700, 1000), (1700, 1500), (2100, 1500), (2100, 1850)]
PATH_6 = [(2850, 1600), (2500, 1600), (2500, 1200), (2200, 1200), (2200, 1000),
          (800, 1000), (800, 600), (400, 600), (400, 300), (150, 300)]
# Line 25 skips the Big Market: it starts with the 43, then heads east to its own end at Ak-Jar
PATH_25 = [(1300, 60), (1300, 650), (1900, 650), (1900, 1350), (2350, 1350)]
# Line 10 crosses the whole city west to east along Main Street, through the Big Market
PATH_10 = [(150, 1100), (700, 1100), (700, 1000), (2700, 1000), (2700, 400)]
# Line 7 runs along the north edge, then down the east side
PATH_7 = [(150, 300), (2400, 300), (2400, 1000), (2700, 1000), (2700, 1850)]
# Line 49 comes from the Western District along Main Street, twins with the 43 for one stop, ends at Kok-Jar
PATH_49 = [(800, 450), (800, 1000), (1700, 1000), (1700, 1600)]
# Line 9 is the quiet western line: its own roads, crossing the river to Nookat Road
PATH_9 = [(300, 750), (300, 1100), (600, 1100), (600, 1750), (1700, 1750)]


def round_trip(path):
    """Out to the far terminal, then back the same way: A B C D -> A B C D C B."""
    return path + path[-2:0:-1]


class Camera:
    """Decides which part of the big world is on screen, and how zoomed in."""

    def __init__(self):
        self.zoom = 0.8
        self.x = 0
        self.y = 0
        self.center_on(1500, 1000)   # start looking at the Big Market

    def view_size(self):
        return MAP_WIDTH / self.zoom, HEIGHT / self.zoom

    def clamp(self):
        w, h = self.view_size()
        self.x = max(0, min(self.x, WORLD_WIDTH - w))
        self.y = max(0, min(self.y, WORLD_HEIGHT - h))

    def center_on(self, wx, wy):
        w, h = self.view_size()
        self.x = wx - w / 2
        self.y = wy - h / 2
        self.clamp()

    def move(self, dx, dy):
        self.x += dx / self.zoom
        self.y += dy / self.zoom
        self.clamp()

    def to_screen(self, wx, wy):
        return (wx - self.x) * self.zoom, (wy - self.y) * self.zoom

    def to_world(self, sx, sy):
        return sx / self.zoom + self.x, sy / self.zoom + self.y

    def zoom_at(self, sx, sy, factor):
        """Zoom in or out, keeping the point under the mouse in place."""
        wx, wy = self.to_world(sx, sy)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        self.x = wx - sx / self.zoom
        self.y = wy - sy / self.zoom
        self.clamp()

    def rect(self, world_rect):
        """A rectangle in the world -> the same rectangle on screen."""
        sx, sy = self.to_screen(world_rect.centerx, world_rect.centery)
        r = pygame.Rect(0, 0, max(1, round(world_rect.width * self.zoom)),
                        max(1, round(world_rect.height * self.zoom)))
        r.center = (round(sx), round(sy))
        return r


camera = Camera()


class Rider:
    """One person with a trip: a list of legs. Each leg = (buses that work, stop to get off at).
    'Buses that work' is a set like {("43", "out"), ("49", "out")}: they take whichever comes first."""
    __slots__ = ("plan", "leg", "born")

    def __init__(self, plan, born):
        self.plan = plan
        self.leg = 0
        self.born = born

    def can_take(self, number, direction):
        return (number, direction) in self.plan[self.leg][0]

    def gets_off_at(self):
        return self.plan[self.leg][1]


class Stop:
    everyone = []   # every stop in the city, in the order they were made

    def __init__(self, name, position, people_per_minute, label="right", terminal=False):
        self.name = name
        self.x, self.y = position
        self.busy = people_per_minute          # also how popular it is as a destination
        self.arrival_chance = people_per_minute / (60 * FPS)
        self.label = label            # which side the sign goes: right, left, above, below
        self.terminal = terminal
        self.lines = []               # which bus lines stop here (filled in by make_line)
        self.waiting = []             # people waiting here (each knows which buses work for them)
        self.arrived = 0              # people who finished their trip here
        self.transfers = 0            # people who changed buses here
        self.gave_up = 0              # people who got tired of waiting here
        self.destinations = []        # places you can reach from here (filled in by the trip planner)
        self.weights = []
        Stop.everyone.append(self)

    def total_waiting(self):
        return len(self.waiting)

    def add_waiting(self, rider):
        self.waiting.append(rider)

    def update(self, multiplier, now):
        # Once a minute: anyone who has waited too long gives up and leaves
        if now % FPS == 0 and self.waiting:
            patient = [r for r in self.waiting if now - r.born < GIVE_UP_MINUTES * FPS]
            quit_count = len(self.waiting) - len(patient)
            if quit_count:
                self.waiting = patient
                self.gave_up += quit_count
                Bus.gave_up += quit_count
        if self.destinations and random.random() < self.arrival_chance * multiplier:
            dest = random.choices(self.destinations, weights=self.weights)[0]
            self.add_waiting(Rider(TRIPS[(self, dest)], now))

    def draw(self, surface, now):
        zoom = camera.zoom
        sx, sy = camera.to_screen(self.x, self.y)
        pygame.draw.circle(surface, SIGN, (round(sx), round(sy)), max(2, round(6 * zoom)))
        if zoom < 0.5:
            return   # too far out to read signs

        total = self.total_waiting()
        if total >= CROWDED:
            bg, fg = SIGN_CROWDED, CRIMSON
        elif self.terminal:
            bg, fg = TERMINAL_SIGN, WHITE
        else:
            bg, fg = SIGN, CRIMSON
        text = get_font(13 * zoom).render(f"{self.name} · {total}", True, fg)

        half = text.get_width() / 2
        if self.label == "right":
            pos = (sx + 85 * zoom + half, sy)
        elif self.label == "left":
            pos = (sx - 85 * zoom - half, sy)
        elif self.label == "above":
            pos = (sx, sy - 78 * zoom)
        else:
            pos = (sx, sy + 78 * zoom)
        sign_rect = text.get_rect(center=(round(pos[0]), round(pos[1])))
        pygame.draw.rect(surface, bg, sign_rect.inflate(10, 6), border_radius=3)
        surface.blit(text, sign_rect)
        if self.terminal:
            draw_dispatcher_board(surface, self, sign_rect.inflate(10, 6), now)


def minutes_left(frames):
    """Frames -> whole simulated minutes, rounded up (1 real second = 1 sim minute)."""
    return max(0, math.ceil(frames / FPS))


def line_by_number(number):
    for line in LINES:
        if line.number == number:
            return line


def draw_dispatcher_board(surface, stop, sign_rect, now):
    """Under a terminal's sign: one row per line with the dispatcher's countdown."""
    zoom = camera.zoom
    font = get_font(12 * zoom)
    rows = []
    for number in stop.lines:
        line = line_by_number(number)
        queue = line.queue.get(stop, [])
        left = line.time_left(stop, now)
        if queue:
            head = queue[0]
            if left > 0:
                text, color = f"{number}: leaves in {minutes_left(left)} min ({len(queue)} in lot)", WHITE
            elif head.wait > 0:
                text, color = f"{number}: time's up - unloading, then leaves", LIGHT_COLORS["yellow"]
            elif head.road_blocked:
                text, color = f"{number}: time's up - road out is full", LIGHT_COLORS["yellow"]
            else:
                text, color = f"{number}: departing now", LIGHT_COLORS["green"]
        else:
            if left > 0:
                text, color = f"{number}: next due in {minutes_left(left)} min (no bus yet)", GRAY
            else:
                text, color = f"{number}: LATE {minutes_left(-left)} min - waiting for a bus", SIGN_CROWDED
        rows.append(font.render(text, True, color))

    width = max(r.get_width() for r in rows) + 12
    height = sum(r.get_height() for r in rows) + 8
    board = pygame.Rect(0, 0, width, height)
    if stop.label == "above":
        board.midbottom = (sign_rect.centerx, sign_rect.top - 6)
    else:
        board.midtop = (sign_rect.centerx, sign_rect.bottom + 6)
    pygame.draw.rect(surface, (15, 15, 15), board, border_radius=4)
    pygame.draw.rect(surface, GRAY, board, 1, border_radius=4)
    y = board.y + 4
    for r in rows:
        surface.blit(r, (board.x + 6, y))
        y += r.get_height()


class MarketStop(Stop):
    """A Stop that draws itself as a big building. Everything else it inherits from Stop."""

    def draw(self, surface, now):
        zoom = camera.zoom
        building = camera.rect(pygame.Rect(self.x - 115, self.y - 140, 230, 72))
        pygame.draw.rect(surface, MARKET_COLOR, building, border_radius=6)
        pygame.draw.rect(surface, CRIMSON, building, max(1, round(3 * zoom)), border_radius=6)
        if zoom >= 0.45:
            title = get_font(24 * zoom).render("BIG MARKET", True, CRIMSON)
            surface.blit(title, title.get_rect(center=(building.centerx, building.centery - 12 * zoom)))
            info = get_font(13 * zoom).render(
                f"{self.total_waiting()} waiting · {self.arrived} shoppers", True, CRIMSON)
            surface.blit(info, info.get_rect(center=(building.centerx, building.centery + 16 * zoom)))
        sx, sy = camera.to_screen(self.x, self.y)
        pygame.draw.circle(surface, SIGN, (round(sx), round(sy)), max(3, round(8 * zoom)))


def find_stop(name):
    """Grab an existing stop by name, so two lines can share the very same stop."""
    for stop in Stop.everyone:
        if stop.name == name:
            return stop


# --- Stops: name, position, how many people show up per minute (= how popular it is) ---
BIG_MARKET = MarketStop("Big Market", (1500, 1000), 70)

STOPS_53 = [
    Stop("Meerkan", (150, 1850), 20, terminal=True, label="below"),
    Stop("Shark", (600, 1650), 15),
    Stop("Nariman", (800, 1400), 15, label="below"),
    Stop("Ak-Buura", (1000, 1200), 20, label="left"),
    BIG_MARKET,
    Stop("Cheremushki", (1900, 800), 25),
    Stop("Sulaiman-Too", (2150, 600), 25, label="above"),
    Stop("Kelechek", (2400, 400), 15),
    Stop("Osh Airport", (2850, 200), 25, terminal=True, label="above"),
]
STOPS_43 = [
    Stop("Osh University", (1300, 60), 35, terminal=True, label="left"),
    Stop("Central Square", (1300, 400), 25),
    Stop("Navoi Street", (1200, 850), 20),
    BIG_MARKET,
    Stop("Amir-Timur", (1700, 1250), 20, label="left"),
    Stop("Japalak", (2000, 1500), 15, label="below"),
    Stop("Kashgar-Kyshtak", (2100, 1700), 20),
    Stop("Kara-Suu", (2100, 1850), 25, terminal=True),
]
STOPS_6 = [
    Stop("Papan", (2850, 1600), 15, terminal=True, label="above"),
    Stop("Hospital", (2500, 1400), 20),
    Stop("Tölöykön", (2350, 1200), 15, label="above"),
    Stop("Bus Station", (2050, 1000), 30, label="below"),
    BIG_MARKET,
    Stop("Furkat", (800, 800), 20),
    Stop("Mady", (600, 600), 15, label="above"),
    Stop("Kyzyl-Kyshtak", (150, 300), 20, terminal=True, label="below"),
]
STOPS_25 = [
    find_stop("Osh University"),        # shared with 43
    find_stop("Central Square"),        # shared with 43
    Stop("City Park", (1600, 650), 20, label="above"),
    find_stop("Cheremushki"),           # shared with 53
    Stop("Kurmanjan Datka", (1900, 1250), 20),
    Stop("Ak-Jar", (2350, 1350), 20, terminal=True, label="above"),
]
STOPS_10 = [
    Stop("Aravan Road", (150, 1100), 15, terminal=True, label="below"),
    Stop("Teshik-Tash", (450, 1100), 30, label="below"),   # from your old CSS map
    find_stop("Big Market"),            # shared with 53, 43, 6
    find_stop("Bus Station"),           # shared with 6
    Stop("Dacha 1", (2550, 1000), 20, label="below"),       # from your old CSS map
    Stop("Surot-Tash", (2700, 700), 20),                    # from your old CSS map
    Stop("Özgön Road", (2700, 400), 15, terminal=True, label="above"),
]
STOPS_7 = [
    find_stop("Kyzyl-Kyshtak"),         # shared with 6
    Stop("Gulbaar", (900, 300), 15, label="above"),
    Stop("Turan", (1650, 300), 20, label="above"),
    Stop("Ak-Tilek", (2050, 300), 15, label="above"),
    find_stop("Kelechek"),              # shared with 53
    find_stop("Dacha 1"),               # shared with 10
    Stop("Kashgar Road", (2700, 1350), 15),
    Stop("Sary-Tash", (2700, 1850), 15, terminal=True),
]
STOPS_49 = [
    Stop("Western District", (800, 450), 20, terminal=True, label="left"),
    find_stop("Furkat"),                # shared with 6
    find_stop("Big Market"),            # shared with 53, 43, 6, 10
    find_stop("Amir-Timur"),            # shared with 43 (the only stretch they twin)
    Stop("Kok-Jar", (1700, 1600), 15, terminal=True),
]
STOPS_9 = [
    Stop("Kerme-Too", (300, 750), 15, terminal=True, label="left"),
    Stop("Kurshab", (300, 950), 15),
    find_stop("Teshik-Tash"),           # shared with 10
    Stop("Kyzyl-Kel", (600, 1250), 15),
    find_stop("Shark"),                 # shared with 53
    Stop("Kenesh", (780, 1750), 15, label="below"),
    Stop("Gulistan", (950, 1750), 15, label="above"),
    Stop("Sary-Bulak", (1350, 1750), 15, label="above"),
    Stop("Nookat Road", (1700, 1750), 15, terminal=True),
]

ALL_STOPS = Stop.everyone   # every stop, each one counted once


class Bus:
    delivered = 0       # shared by all buses: people who finished their trip
    trip_minutes = 0    # total minutes those trips took (for the average)
    transfers = 0       # people who changed buses
    breakdowns = 0
    gave_up = 0         # people who waited too long and left
    fleet = []          # every bus in the city

    def __init__(self, line, color, text_color, home, order):
        self.line = line
        self.number = line.number
        self.color = color
        self.text_color = text_color
        self.map_color = line.map_color
        self.route = route = line.route
        self.stops = line.stops
        self.speed = line.speed
        self.capacity = line.capacity
        self.riders = []
        # Start at the home terminal: the first one, or the far one (end of the outbound path)
        start = 0 if home is line.stops[0] else len(line.path) - 1
        self.x, self.y = route[start]
        self.target = (start + 1) % len(route)
        self.wait = 0
        self.at_terminal = home       # waiting for the dispatcher at this terminal
        self.status = f"At {home.name}: in the lot"
        self.parked = True            # every bus starts the day parked in its terminal lot
        self.broken = False
        self.road_blocked = False     # ready to leave, but the road out is full
        self.slot = 0
        self.lot_since = order - 10_000   # morning order: who leaves first
        self.last_stop = home         # starting at a terminal counts as "just served it"

        # Parked facing INTO the terminal, like a bus that just arrived
        dx = route[self.target][0] - self.x
        dy = route[self.target][1] - self.y
        length = math.hypot(dx, dy)
        self.heading = (-dx / length, -dy / length)

        Bus.fleet.append(self)

    @property
    def passengers(self):
        return len(self.riders)

    def direction(self):
        """'out' on the way to the far terminal, 'back' on the way home."""
        return "out" if 1 <= self.target <= len(self.line.path) - 1 else "back"

    def blocked(self):
        """Is ANY bus (any line) right in front of me, in my lane, going my way?"""
        hx, hy = self.heading
        for other in Bus.fleet:
            if other is self or other.parked:
                continue
            ox, oy = other.heading
            if hx * ox + hy * oy < 0.9:
                continue
            rx = other.x - self.x
            ry = other.y - self.y
            ahead = rx * hx + ry * hy
            side = abs(rx * hy - ry * hx)
            if 0 < ahead < SAFE_GAP and side < 5:
                return True
        return False

    def board(self, stop):
        """People who can use MY line in MY direction get on, until the bus is full."""
        direction = self.direction()
        free_seats = self.capacity - self.passengers
        getting_on, still_waiting = [], []
        for rider in stop.waiting:            # first come, first served
            if len(getting_on) < free_seats and rider.can_take(self.number, direction):
                getting_on.append(rider)
            else:
                still_waiting.append(rider)
        stop.waiting = still_waiting
        self.riders += getting_on
        self.line.boardings += len(getting_on)
        self.line.revenue += len(getting_on) * FARE
        return len(getting_on)

    def red_light(self, now):
        """Am I right at a stop line, and is the light for my direction not green?"""
        hx, hy = self.heading
        direction = "EW" if abs(hx) > abs(hy) else "NS"
        for light in LIGHTS:
            rx = light.x - self.x
            ry = light.y - self.y
            ahead = rx * hx + ry * hy
            side = abs(rx * hy - ry * hx)
            if side < 5 and STOP_LINE < ahead <= STOP_LINE + self.speed + 0.5:
                if light.color_for(direction, now) != "green":
                    return True
        return False

    def serve_stop(self, stop, now):
        # Get off: people whose stop this is (at a terminal, everyone - it's the end of the line)
        staying = []
        getting_off = 0
        for rider in self.riders:
            if rider.gets_off_at() is stop or stop.terminal:
                getting_off += 1
                if rider.gets_off_at() is stop and rider.leg + 1 < len(rider.plan):
                    rider.leg += 1                  # change buses here
                    stop.add_waiting(rider)
                    stop.transfers += 1
                    Bus.transfers += 1
                else:
                    stop.arrived += 1               # trip finished
                    Bus.delivered += 1
                    Bus.trip_minutes += (now - rider.born) / FPS
                    if rider.gets_off_at() is not stop:
                        LOST_RIDERS.append(rider)   # should never happen: checked by the tests
            else:
                staying.append(rider)
        self.riders = staying

        getting_on = 0 if stop.terminal else self.board(stop)   # at a terminal, riders board when it leaves
        self.status = f"Unloading at {stop.name}" if stop.terminal else f"Loading at {stop.name}"

        seconds = BASE_DWELL + (getting_off + getting_on) * SECONDS_PER_PERSON
        if stop.terminal:
            # The terminal is also the end of the road: point the bus at its NEXT corner now.
            # (Bug fix: before, its first move "arrived" here again, so it unloaded twice
            #  and rejoined the back of the line, restarting the countdown.)
            while self.route[self.target] == (self.x, self.y):
                self.target = (self.target + 1) % len(self.route)
            self.lot_since = now
            self.at_terminal = stop
            self.line.join_queue(self, stop)   # get in line for the dispatcher
            first_in_line = self.line.queue[stop][0] is self
            if first_in_line and self.line.time_left(stop, now) <= 0:
                seconds = BASE_DWELL           # running late: quick swap of passengers, then go
        self.wait = int(seconds * FPS)

        # Pull into the bus bay, taking the first free spot
        taken = set()
        for other in Bus.fleet:
            if other is not self and other.parked and other.last_stop is stop:
                ox, oy = other.heading
                if ox * self.heading[0] + oy * self.heading[1] > 0.9:
                    taken.add(other.slot)
        self.slot = 0
        while self.slot in taken:
            self.slot += 1
        self.parked = True

    def try_to_leave_terminal(self, now):
        """Ask the dispatcher; then make sure the road out is actually clear before going."""
        terminal = self.at_terminal
        if not self.line.may_depart(self, terminal, now):
            queue = self.line.queue[terminal]
            ahead = queue.index(self)
            if ahead == 0:
                minutes = minutes_left(self.line.time_left(terminal, now))
                self.status = f"At {terminal.name}: leaves in {minutes} min"
            else:
                self.status = f"At {terminal.name}: {ahead} bus(es) ahead in line"
            return False

        # Look down the road I'm about to drive on
        while self.route[self.target] == (self.x, self.y):
            self.target = (self.target + 1) % len(self.route)
        tx, ty = self.route[self.target]
        dx, dy = tx - self.x, ty - self.y
        length = math.hypot(dx, dy)
        facing_in = self.heading
        self.heading = (dx / length, dy / length)
        if self.blocked():
            self.heading = facing_in
            self.road_blocked = True
            self.status = f"At {terminal.name}: ready, road out is full"
            return False

        # Go! The countdown for the next bus starts NOW, when this one really leaves
        self.road_blocked = False
        self.line.depart(self, terminal, now)
        self.board(terminal)   # riders get on as the doors open for departure
        self.at_terminal = None
        return True

    def update(self, now):
        if self.wait > 0:
            self.wait -= 1
            return

        if self.at_terminal is not None and not self.try_to_leave_terminal(now):
            return

        self.parked = False
        self.broken = False

        for stop in self.stops:
            if stop is not self.last_stop:
                if math.hypot(stop.x - self.x, stop.y - self.y) <= self.speed:
                    self.x, self.y = stop.x, stop.y
                    self.last_stop = stop
                    self.serve_stop(stop, now)
                    return

        if self.red_light(now):
            self.status = "Stopped at a red light"
            return

        if self.blocked():
            self.status = "Stuck in traffic"
            return

        # Breakdowns: rare, but they happen
        if random.random() < BREAKDOWNS_PER_HOUR / (60 * FPS):
            self.broken = True
            self.parked = True             # pulls over so traffic can pass
            self.wait = REPAIR_MINUTES * FPS
            self.status = f"Broken down! Repair takes {REPAIR_MINUTES} min"
            Bus.breakdowns += 1
            return

        self.status = "Driving"
        tx, ty = self.route[self.target]
        dx = tx - self.x
        dy = ty - self.y
        distance = math.hypot(dx, dy)

        if distance <= self.speed:
            self.x, self.y = tx, ty
            self.target = (self.target + 1) % len(self.route)
            self.last_stop = None
        else:
            self.heading = (dx / distance, dy / distance)
            self.x += self.heading[0] * self.speed
            self.y += self.heading[1] * self.speed

    def in_terminal_lot(self):
        return self.at_terminal is not None and self.parked and not self.broken

    def world_rect(self):
        """Where the bus sits in the world: right-hand lane, bus bay, or terminal lot."""
        hx, hy = self.heading
        vertical = abs(hy) > abs(hx)
        width, height = (20, 60) if vertical else (60, 20)

        side = LANE_OFFSET           # "right" of a direction (hx, hy) is (-hy, hx)
        back = 0
        if self.in_terminal_lot():
            side = LANE_OFFSET + 24 + self.lot_position() * 26   # terminal lot: side by side
        elif self.parked and not self.broken:
            side = LANE_OFFSET + 24                    # bus bay beside the road
            back = self.slot * 64                      # queue behind buses already there
        elif self.broken:
            side = LANE_OFFSET + 24                    # pulled over on the shoulder
        cx = self.x - hy * side - hx * back
        cy = self.y + hx * side - hy * back

        rect = pygame.Rect(0, 0, width, height)
        rect.center = (round(cx), round(cy))
        return rect, vertical

    def lot_position(self):
        """Place in the terminal lot: buses that arrived earlier park nearer the road."""
        place = 0
        for other in Bus.fleet:
            if (other is not self and other.in_terminal_lot()
                    and other.at_terminal is self.at_terminal and other.lot_since < self.lot_since):
                ox, oy = other.heading
                if ox * self.heading[0] + oy * self.heading[1] > 0.9:
                    place += 1
        return place

    def draw_bay(self, surface):
        if self.parked:
            rect, vertical = self.world_rect()
            grow = (8, 12) if vertical else (12, 8)
            pygame.draw.rect(surface, ROAD, camera.rect(rect.inflate(*grow)), border_radius=4)

    def draw(self, surface, now):
        hx, hy = self.heading
        zoom = camera.zoom
        world, vertical = self.world_rect()
        rect = camera.rect(world)
        if not rect.colliderect(surface.get_rect()):
            return
        pygame.draw.rect(surface, self.color, rect, border_radius=max(1, round(4 * zoom)))
        if self.broken and (now // 30) % 2 == 0:
            pygame.draw.rect(surface, LIGHT_COLORS["red"], rect.inflate(6, 6), 3, border_radius=5)

        if zoom >= 0.55:
            label = get_font(15 * zoom).render(self.number, True, self.text_color)
            if vertical:
                label = pygame.transform.rotate(label, 90)
            surface.blit(label, label.get_rect(center=rect.center))

        if zoom >= 0.8 and not self.in_terminal_lot():
            push = (30 if vertical else 22) * zoom
            load = get_font(13 * zoom).render(f"{self.passengers}/{self.capacity}", True, WHITE)
            cx, cy = rect.center
            surface.blit(load, load.get_rect(center=(round(cx - hy * push), round(cy + hx * push))))


class Line:
    """A bus line, with a dispatcher at each terminal who keeps buses 'interval' apart."""

    def __init__(self, number, path, stops, count, interval_minutes, speed, capacity, colors, map_color):
        self.number = number
        self.path = path
        self.route = round_trip(path)
        self.stops = stops
        self.count = count
        self.interval_minutes = interval_minutes
        self.interval = interval_minutes * FPS   # in frames (1 sim minute = 1 real second)
        self.speed = speed
        self.capacity = capacity
        self.map_color = map_color
        self.queue = {}            # terminal -> buses in the lot, first come first served
        self.last_departure = {}   # terminal -> the frame the last bus actually left
        self.boardings = 0
        self.revenue = 0
        self.cost = 0

        # The order this line visits its stops on the way out (0 = first terminal)
        ordered = sorted(stops, key=lambda s: distance_along(path, (s.x, s.y)))
        self.position = {stop: i for i, stop in enumerate(ordered)}

        for stop in stops:
            stop.lines.append(number)

        # Buses sleep in the lots at BOTH ends, so service starts from both terminals at 06:00
        self.buses = []
        for i in range(count):
            color, text_color = colors[i % len(colors)]
            home = stops[0] if i % 2 == 0 else stops[-1]
            bus = Bus(self, color, text_color, home, order=i)
            self.buses.append(bus)
            self.join_queue(bus, home)

    def join_queue(self, bus, terminal):
        self.queue.setdefault(terminal, []).append(bus)

    def may_depart(self, bus, terminal, now):
        """Has 'interval' passed since the last bus really left, and is this bus first in the lot?"""
        lot = self.queue.get(terminal, [])
        return self.time_left(terminal, now) <= 0 and lot and lot[0] is bus

    def depart(self, bus, terminal, now):
        self.queue[terminal].pop(0)
        self.last_departure[terminal] = now

    def time_left(self, terminal, now):
        """Frames until the next bus is allowed to leave (0 or less = it's time)."""
        last = self.last_departure.get(terminal)
        if last is None:
            return 0
        return self.interval - (now - last)

    def on_road(self):
        return sum(1 for bus in self.buses if bus.at_terminal is None)

    def pay_costs(self):
        """Every frame, each bus costs a little money: more on the road, less waiting."""
        for bus in self.buses:
            per_minute = IDLE_COST if bus.at_terminal is not None else RUNNING_COST
            self.cost += per_minute / FPS

    def profit(self):
        return self.revenue - self.cost


LINES = []
LIGHTS = []
LOST_RIDERS = []
TRIPS = {}            # (from stop, to stop) -> the trip plan
lights_on = True


class TrafficLight:
    """Takes turns: east-west gets green, then north-south, with yellow in between."""

    def __init__(self, x, y, arms):
        self.x, self.y = x, y
        self.arms = arms
        self.cycle = int(2 * (GREEN_TIME + YELLOW_TIME) * FPS)
        self.offset = random.randint(0, self.cycle)

    def color_for(self, direction, now):
        if not lights_on:
            return "green"
        green = GREEN_TIME * FPS
        yellow = YELLOW_TIME * FPS
        t = (now + self.offset) % self.cycle
        if direction == "NS":
            t = (t - green - yellow) % self.cycle
        if t < green:
            return "green"
        if t < green + yellow:
            return "yellow"
        return "red"

    def draw(self, surface, now):
        zoom = camera.zoom
        for ax, ay in self.arms:
            direction = "EW" if ax != 0 else "NS"
            color = LIGHT_COLORS[self.color_for(direction, now)] if lights_on else LIGHT_COLORS["off"]
            rx, ry = ay, -ax
            stop_x = self.x + ax * STOP_LINE
            stop_y = self.y + ay * STOP_LINE
            a = camera.to_screen(stop_x + rx * 3, stop_y + ry * 3)
            b = camera.to_screen(stop_x + rx * 21, stop_y + ry * 21)
            pygame.draw.line(surface, color, a, b, max(2, round(5 * zoom)))
            lamp = camera.to_screen(stop_x + rx * 32, stop_y + ry * 32)
            pygame.draw.circle(surface, BLACK, (round(lamp[0]), round(lamp[1])), max(3, round(8 * zoom)))
            pygame.draw.circle(surface, color, (round(lamp[0]), round(lamp[1])), max(2, round(6 * zoom)))


def find_junctions():
    """Find every spot where 3 or more streets meet, and put a traffic light there."""
    segments = []
    for line in LINES:
        segments += list(zip(line.path, line.path[1:]))

    candidates = set()
    for a, b in segments:
        candidates.add(a)
        candidates.add(b)
    for a, b in segments:
        for c, d in segments:
            if a[1] == b[1] and c[0] == d[0]:
                point = (c[0], a[1])
                if on_segment(point, a, b) and on_segment(point, c, d):
                    candidates.add(point)

    for point in candidates:
        arms = set()
        for a, b in segments:
            if on_segment(point, a, b):
                for end in (a, b):
                    if end != point:
                        arms.add((sign(end[0] - point[0]), sign(end[1] - point[1])))
        if len(arms) >= 3:
            LIGHTS.append(TrafficLight(point[0], point[1], sorted(arms)))


def make_line(number, path, stops, count, interval_minutes, speed, capacity, colors, map_color):
    LINES.append(Line(number, path, stops, count, interval_minutes, speed, capacity, colors, map_color))


def direction_on(line, origin, dest):
    return "out" if line.position[dest] > line.position[origin] else "back"


def leg(origin, dest):
    """One bus ride from origin to dest: EVERY line that connects them works, plus where to get off."""
    options = frozenset((line.number, direction_on(line, origin, dest)) for line in LINES
                        if origin in line.position and dest in line.position)
    return (options, dest)


def plan_trip(origin, dest):
    """Find the best way from one stop to another: one bus if possible, otherwise one transfer."""
    best, best_cost = None, None
    for line in LINES:
        if origin in line.position and dest in line.position:
            cost = abs(line.position[dest] - line.position[origin])
            if best is None or cost < best_cost:
                best, best_cost = [leg(origin, dest)], cost
    if best:
        return best
    for first in LINES:
        if origin not in first.position:
            continue
        for second in LINES:
            if second is first or dest not in second.position:
                continue
            for change in first.stops:
                if change in second.position and change is not origin and change is not dest:
                    cost = (abs(first.position[change] - first.position[origin])
                            + abs(second.position[dest] - second.position[change]) + TRANSFER_PENALTY)
                    if best is None or cost < best_cost:
                        best = [leg(origin, change), leg(change, dest)]
                        best_cost = cost
    return best


def build_trip_planner():
    """Work out every trip once at the start, so riders know their route instantly."""
    for origin in ALL_STOPS:
        for dest in ALL_STOPS:
            if dest is origin:
                continue
            plan = plan_trip(origin, dest)
            if plan:
                TRIPS[(origin, dest)] = plan
                origin.destinations.append(dest)
                origin.weights.append(dest.busy)   # busy places are popular places to go


def build_background():
    """Draw everything that never moves (grass, river, roads) ONCE onto a big picture."""
    world = pygame.Surface((WORLD_WIDTH, WORLD_HEIGHT))
    world.fill(GRASS)
    pygame.draw.lines(world, RIVER, False, RIVER_PATH, 60)
    for point in RIVER_PATH:
        pygame.draw.circle(world, RIVER, point, 30)
    river_name = get_font(22).render("Ak-Buura River", True, WHITE)
    world.blit(pygame.transform.rotate(river_name, 90), (1150, 1300))

    for line in LINES:
        pygame.draw.lines(world, ROAD, False, line.path, ROAD_WIDTH)
        for point in line.path:
            pygame.draw.circle(world, ROAD, point, ROAD_WIDTH // 2)
    for line in LINES:
        pygame.draw.lines(world, CENTER_LINE, False, line.path, 2)
    return world


def draw_world_view(background):
    """Copy the part of the world the camera sees onto the screen, scaled by zoom."""
    w, h = camera.view_size()
    view = pygame.Rect(int(camera.x), int(camera.y), int(w), int(h)).clip(background.get_rect())
    part = background.subsurface(view)
    if camera.zoom == 1:
        screen.blit(part, (0, 0))
    else:
        screen.blit(pygame.transform.scale(part, (MAP_WIDTH, HEIGHT)), (0, 0))


night_overlay = pygame.Surface((MAP_WIDTH, HEIGHT))
night_overlay.fill(NIGHT_COLOR)


def draw_night(hour_float):
    amount = darkness(hour_float)
    if amount > 0:
        night_overlay.set_alpha(int(amount * 255))
        screen.blit(night_overlay, (0, 0))


MINIMAP_W = PANEL_WIDTH - 30
MINIMAP_H = round(MINIMAP_W * WORLD_HEIGHT / WORLD_WIDTH)
MINIMAP_POS = (MAP_WIDTH + 15, HEIGHT - MINIMAP_H - 15)
MINIMAP_SCALE = MINIMAP_W / WORLD_WIDTH


def minimap_rect():
    return pygame.Rect(MINIMAP_POS[0], MINIMAP_POS[1], MINIMAP_W, MINIMAP_H)


def clock_text(sim_minutes):
    hours = int(sim_minutes // 60) % 24
    minutes = int(sim_minutes % 60)
    return f"{hours:02d}:{minutes:02d}"


def average_trip():
    return Bus.trip_minutes / Bus.delivered if Bus.delivered else 0


def total_profit():
    return sum(line.profit() for line in LINES)


def draw_panel(sim_minutes, multiplier, minimap):
    pygame.draw.rect(screen, PANEL_BG, (MAP_WIDTH, 0, PANEL_WIDTH, HEIGHT))
    x = MAP_WIDTH + 16
    small_font = get_font(13)

    screen.blit(get_font(44).render(clock_text(sim_minutes), True, WHITE), (x, 15))
    if paused:
        speed_text, speed_color = "PAUSED", LIGHT_COLORS["yellow"]
    else:
        speed_text, speed_color = f"{SPEEDS[speed_index]}x", LIGHT_COLORS["green"]
    speed_surface = get_font(16).render(speed_text, True, speed_color)
    screen.blit(speed_surface, (WIDTH - 12 - speed_surface.get_width(), 30))

    if multiplier > 1:
        status, color = "RUSH HOUR", SIGN_CROWDED
    elif multiplier < 1:
        status, color = "Night", GRAY
    else:
        status, color = "Normal day", WHITE
    screen.blit(get_font(17).render(status, True, color), (x, 68))

    y = 105
    screen.blit(small_font.render("line · interval · out/total", True, GRAY), (x, y))
    y += 20
    for line in LINES:
        pygame.draw.circle(screen, line.map_color, (x + 5, y + 9), 5)
        screen.blit(get_font(16).render(f"Line {line.number}", True, SIGN), (x + 16, y))
        info = small_font.render(f"{line.interval_minutes} min · {line.on_road()}/{line.count}", True, GRAY)
        screen.blit(info, (WIDTH - 12 - info.get_width(), y + 2))
        ends = f"{line.stops[0].name} - {line.stops[-1].name}"
        screen.blit(small_font.render(ends, True, WHITE), (x + 16, y + 19))
        y += 38

    waiting = sum(stop.total_waiting() for stop in ALL_STOPS)
    riding = sum(bus.passengers for bus in Bus.fleet)
    profit = total_profit()
    y += 4
    rows = [
        (f"Waiting {waiting:,} · Riding {riding:,}", WHITE),
        (f"Delivered {Bus.delivered:,} · trip {average_trip():.0f}m", WHITE),
        (f"Gave up {Bus.gave_up:,}", WHITE),
        (f"Profit {profit:+,.0f} som", LIGHT_COLORS["green"] if profit >= 0 else SIGN_CROWDED),
    ]
    for text, color in rows:
        screen.blit(get_font(13).render(text, True, color), (x, y))
        y += 19
    light_text = f"Lights {'ON' if lights_on else 'OFF'} · Breakdowns {Bus.breakdowns}"
    screen.blit(small_font.render(light_text, True, GRAY), (x, y + 2))
    y += 19
    screen.blit(get_font(12).render("H help · G stats · Space pause", True, GRAY), (x, y))

    # Minimap: the whole city, tiny
    screen.blit(minimap, MINIMAP_POS)
    for bus in Bus.fleet:
        mx = MINIMAP_POS[0] + bus.x * MINIMAP_SCALE
        my = MINIMAP_POS[1] + bus.y * MINIMAP_SCALE
        color = LIGHT_COLORS["red"] if bus.broken else bus.map_color
        pygame.draw.circle(screen, color, (round(mx), round(my)), 2)
        if bus is selected:
            pygame.draw.circle(screen, WHITE, (round(mx), round(my)), 5, 1)
    w, h = camera.view_size()
    view = pygame.Rect(round(MINIMAP_POS[0] + camera.x * MINIMAP_SCALE),
                       round(MINIMAP_POS[1] + camera.y * MINIMAP_SCALE),
                       round(w * MINIMAP_SCALE), round(h * MINIMAP_SCALE))
    pygame.draw.rect(screen, WHITE, view, 1)


def draw_card(rect, border_color):
    pygame.draw.rect(screen, PANEL_BG, rect, border_radius=10)
    pygame.draw.rect(screen, border_color, rect, 2, border_radius=10)


HELP_LINES = [
    ("Moving around", None),
    ("Arrows / WASD / drag the map", "move the camera"),
    ("Mouse wheel, + / -, Q / E", "zoom in and out"),
    ("Click the minimap", "jump anywhere"),
    ("Click a bus", "follow it (Esc lets go)"),
    ("Time", None),
    ("Space", "pause / continue"),
    ("1  2  3  4", "speed 1x, 2x, 5x, 10x"),
    ("City", None),
    ("L", "traffic lights on / off"),
    ("G", "statistics: chart + money per line"),
    ("X", "save the statistics as CSV files"),
    ("H", "show / hide this help"),
]


def draw_help():
    card = pygame.Rect(0, 0, 560, 420)
    card.center = (MAP_WIDTH // 2, HEIGHT // 2)
    draw_card(card, SIGN)
    y = card.y + 18
    screen.blit(get_font(24).render("Controls", True, SIGN), (card.x + 24, y))
    y += 40
    for key, meaning in HELP_LINES:
        if meaning is None:
            y += 6
            screen.blit(get_font(15).render(key, True, LIGHT_COLORS["yellow"]), (card.x + 24, y))
            y += 22
            continue
        screen.blit(get_font(14).render(key, True, WHITE), (card.x + 36, y))
        screen.blit(get_font(14).render(meaning, True, GRAY), (card.x + 290, y))
        y += 21


def draw_chart(area, series, title):
    """A simple line chart: series = [(name, color, [values...]), ...] sampled every hour."""
    pygame.draw.rect(screen, (15, 15, 15), area, border_radius=6)
    screen.blit(get_font(15).render(title, True, WHITE), (area.x + 10, area.y + 6))
    inner = area.inflate(-60, -60)
    inner.y += 10
    longest = max((len(values) for _, _, values in series), default=0)
    peak = max((max(values) for _, _, values in series if values), default=1) or 1
    pygame.draw.line(screen, GRAY, inner.bottomleft, inner.bottomright, 1)
    pygame.draw.line(screen, GRAY, inner.bottomleft, inner.topleft, 1)
    screen.blit(get_font(11).render(f"{peak:,.0f}", True, GRAY), (area.x + 6, inner.top - 6))
    screen.blit(get_font(11).render("0", True, GRAY), (area.x + 18, inner.bottom - 6))
    if longest < 2:
        msg = get_font(13).render("Collecting data... one point every simulated hour", True, GRAY)
        screen.blit(msg, msg.get_rect(center=inner.center))
        return
    for i in range(longest):
        if i % 2 == 0:
            label = get_font(11).render(f"{(START_HOUR + i + 1) % 24:02d}h", True, GRAY)
            px = inner.x + inner.width * i / (longest - 1)
            screen.blit(label, (px - 10, inner.bottom + 4))
    legend_x = area.right - 10
    for name, color, values in reversed(series):
        points = [(inner.x + inner.width * i / (longest - 1), inner.bottom - inner.height * v / peak)
                  for i, v in enumerate(values)]
        if len(points) >= 2:
            pygame.draw.lines(screen, color, False, points, 2)
        text = get_font(12).render(name, True, color)
        legend_x -= text.get_width() + 14
        screen.blit(text, (legend_x, area.y + 8))


def draw_stats():
    card = pygame.Rect(20, 20, MAP_WIDTH - 40, HEIGHT - 40)
    draw_card(card, LIGHT_COLORS["green"])
    screen.blit(get_font(24).render("Statistics", True, LIGHT_COLORS["green"]), (card.x + 20, card.y + 14))
    summary = (f"Delivered {Bus.delivered:,} · gave up {Bus.gave_up:,} · average trip {average_trip():.0f} min · "
               f"transfers {Bus.transfers:,} · breakdowns {Bus.breakdowns}")
    screen.blit(get_font(14).render(summary, True, WHITE), (card.x + 20, card.y + 48))

    chart = pygame.Rect(card.x + 20, card.y + 76, card.width - 40, 250)
    draw_chart(chart, [
        ("Waiting", SIGN_CROWDED, [h["waiting"] for h in HISTORY]),
        ("Riding", LIGHT_COLORS["yellow"], [h["riding"] for h in HISTORY]),
        ("Delivered per hour", LIGHT_COLORS["green"], [h["delivered_this_hour"] for h in HISTORY]),
        ("Gave up per hour", GRAY, [h["gave_up_this_hour"] for h in HISTORY]),
    ], "Every simulated hour")

    # Money table
    y = chart.bottom + 18
    columns = [("Line", 20), ("Buses", 110), ("Rides", 190), ("Fares", 290), ("Costs", 410),
               ("Profit", 530), ("Per bus", 660)]
    for name, cx in columns:
        screen.blit(get_font(14).render(name, True, SIGN), (card.x + cx, y))
    y += 24
    for line in LINES:
        pygame.draw.circle(screen, line.map_color, (card.x + 12, y + 8), 5)
        profit = line.profit()
        values = [line.number, str(line.count), f"{line.boardings:,}", f"{line.revenue:,.0f}",
                  f"{line.cost:,.0f}", f"{profit:+,.0f}", f"{profit / line.count:+,.0f}"]
        for (name, cx), value in zip(columns, values):
            color = WHITE
            if name in ("Profit", "Per bus"):
                color = LIGHT_COLORS["green"] if profit >= 0 else SIGN_CROWDED
            screen.blit(get_font(14).render(value, True, color), (card.x + cx, y))
        y += 22
    note = f"Money in som · fare {FARE} per ride · bus costs {RUNNING_COST}/min driving, {IDLE_COST}/min waiting"
    screen.blit(get_font(12).render(note, True, GRAY), (card.x + 20, card.bottom - 26))
    hint = get_font(12).render("G: close · X: save as CSV", True, GRAY)
    screen.blit(hint, (card.right - hint.get_width() - 20, card.bottom - 26))


def record_hour(now):
    waiting = sum(stop.total_waiting() for stop in ALL_STOPS)
    riding = sum(bus.passengers for bus in Bus.fleet)
    before = HISTORY[-1]["delivered"] if HISTORY else 0
    quit_before = HISTORY[-1]["gave_up"] if HISTORY else 0
    HISTORY.append({
        "time": clock_text(START_HOUR * 60 + now / FPS),
        "waiting": waiting,
        "riding": riding,
        "delivered": Bus.delivered,
        "delivered_this_hour": Bus.delivered - before,
        "gave_up": Bus.gave_up,
        "gave_up_this_hour": Bus.gave_up - quit_before,
        "average_trip_min": round(average_trip(), 1),
        "transfers": Bus.transfers,
        "breakdowns": Bus.breakdowns,
        "profit_som": round(total_profit()),
    })


def export_csv():
    """Save the hourly history and the per-line money table next to this script."""
    hours_file = os.path.join(HERE, "bus_stats_hourly.csv")
    with open(hours_file, "w", newline="", encoding="utf-8") as f:
        if HISTORY:
            writer = csv.DictWriter(f, fieldnames=list(HISTORY[0].keys()))
            writer.writeheader()
            writer.writerows(HISTORY)
    lines_file = os.path.join(HERE, "bus_stats_lines.csv")
    with open(lines_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["line", "buses", "interval_min", "rides", "fares_som", "costs_som", "profit_som"])
        for line in LINES:
            writer.writerow([line.number, line.count, line.interval_minutes, line.boardings,
                             round(line.revenue), round(line.cost), round(line.profit())])
    return "Saved bus_stats_hourly.csv and bus_stats_lines.csv"


# --- The lines: make the count / interval / speed numbers your own ---
make_line("53", PATH_53, STOPS_53, count=13, interval_minutes=25, speed=1, capacity=25,
          colors=[((0, 100, 0), WHITE), ((139, 0, 0), WHITE), ((47, 79, 79), WHITE)],
          map_color=(80, 220, 80))
make_line("43", PATH_43, STOPS_43, count=15, interval_minutes=10, speed=1, capacity=25,
          colors=[((255, 255, 0), (0, 0, 139)), (WHITE, BLACK)],
          map_color=(255, 230, 0))
make_line("6", PATH_6, STOPS_6, count=12, interval_minutes=15, speed=1, capacity=25,
          colors=[((0, 0, 139), WHITE), ((218, 165, 32), BLACK), (BLACK, GRAY)],
          map_color=(90, 160, 255))
make_line("25", PATH_25, STOPS_25, count=14, interval_minutes=8, speed=1, capacity=25,
          colors=[((128, 0, 128), WHITE), ((255, 140, 0), BLACK)],
          map_color=(220, 120, 255))
make_line("10", PATH_10, STOPS_10, count=14, interval_minutes=12, speed=1, capacity=25,
          colors=[((178, 34, 34), WHITE), ((240, 240, 240), (178, 34, 34))],
          map_color=(255, 90, 90))
make_line("7", PATH_7, STOPS_7, count=12, interval_minutes=15, speed=1, capacity=25,
          colors=[((0, 128, 128), WHITE), ((70, 70, 70), WHITE)],
          map_color=(0, 220, 200))
make_line("49", PATH_49, STOPS_49, count=10, interval_minutes=12, speed=1, capacity=25,
          colors=[((0, 90, 160), WHITE), ((230, 230, 230), (0, 90, 160))],
          map_color=(240, 240, 240))
make_line("9", PATH_9, STOPS_9, count=8, interval_minutes=15, speed=1, capacity=25,
          colors=[((110, 70, 30), WHITE), ((200, 170, 120), BLACK)],
          map_color=(210, 160, 90))

find_junctions()
build_trip_planner()
background = build_background()
minimap = pygame.transform.smoothscale(background, (MINIMAP_W, MINIMAP_H))
HISTORY = []


def bus_at(pos):
    """Which bus (if any) is under the mouse?"""
    for bus in reversed(Bus.fleet):
        rect = camera.rect(bus.world_rect()[0]).inflate(8, 8)
        if rect.collidepoint(pos):
            return bus
    return None


def draw_selection():
    """White box around the chosen bus, plus an info card in the corner."""
    if selected is None:
        return
    bus = selected
    rect = camera.rect(bus.world_rect()[0]).inflate(10, 10)
    pygame.draw.rect(screen, WHITE, rect, 2, border_radius=5)

    line = bus.line
    heading_to = line.stops[-1].name if bus.direction() == "out" else line.stops[0].name
    number_in_line = line.buses.index(bus) + 1
    # Where are the riders going? Show the most common next stop
    next_offs = {}
    for rider in bus.riders:
        name = rider.gets_off_at().name
        next_offs[name] = next_offs.get(name, 0) + 1
    if next_offs:
        top = max(next_offs, key=next_offs.get)
        riders_text = f"Most get off at {top} ({next_offs[top]})"
    else:
        riders_text = "Empty"

    card = pygame.Rect(12, 12, 320, 132)
    draw_card(card, bus.map_color)
    rows = [
        (get_font(18), f"Line {bus.number}  ·  bus #{number_in_line}", SIGN),
        (get_font(14), f"Heading to {heading_to}", WHITE),
        (get_font(14), f"Passengers: {bus.passengers}/{bus.capacity}", WHITE),
        (get_font(13), riders_text, GRAY),
        (get_font(14), bus.status, LIGHT_COLORS["red"] if bus.broken else LIGHT_COLORS["yellow"]),
        (get_font(12), "Esc or drag the map to let go", GRAY),
    ]
    y = card.y + 8
    for font, text, color in rows:
        screen.blit(font.render(text, True, color), (card.x + 12, y))
        y += font.get_height() + 2


def simulate_one_step(now):
    """Everything that happens in one simulated frame."""
    hour = int((START_HOUR * 60 + now / FPS) // 60) % 24
    multiplier = demand_multiplier(hour)
    for stop in ALL_STOPS:
        stop.update(multiplier, now)
    for bus in Bus.fleet:
        bus.update(now)
    for line in LINES:
        line.pay_costs()
    if now > 0 and now % (60 * FPS) == 0:
        record_hour(now)


# --- Main loop ---
frame = 0
dragging = False
drag_distance = 0
selected = None     # the bus you clicked on
following = False   # is the camera following it?
paused = False
speed_index = 0
show_help = False
show_stats = False
toast, toast_until = "", 0
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_l:
                lights_on = not lights_on
            elif event.key == pygame.K_ESCAPE:
                selected, following, show_help, show_stats = None, False, False, False
            elif event.key == pygame.K_SPACE:
                paused = not paused
            elif event.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                speed_index = [pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4].index(event.key)
                paused = False
            elif event.key == pygame.K_h:
                show_help, show_stats = not show_help, False
            elif event.key == pygame.K_g:
                show_stats, show_help = not show_stats, False
            elif event.key == pygame.K_x:
                toast, toast_until = export_csv(), pygame.time.get_ticks() + 3000
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if event.pos[0] < MAP_WIDTH:
                dragging = True
                drag_distance = 0
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            if dragging and drag_distance < 5:      # a click, not a drag
                selected = bus_at(event.pos)
                following = selected is not None
            dragging = False
        elif event.type == pygame.MOUSEMOTION and dragging:
            drag_distance += abs(event.rel[0]) + abs(event.rel[1])
            if drag_distance >= 5:
                following = False
                camera.move(-event.rel[0], -event.rel[1])
        elif event.type == pygame.MOUSEWHEEL:
            mx, my = pygame.mouse.get_pos()
            if mx < MAP_WIDTH:
                camera.zoom_at(mx, my, 1.1 if event.y > 0 else 1 / 1.1)

    if pygame.mouse.get_pressed()[0] and minimap_rect().collidepoint(pygame.mouse.get_pos()):
        mx, my = pygame.mouse.get_pos()
        camera.center_on((mx - MINIMAP_POS[0]) / MINIMAP_SCALE, (my - MINIMAP_POS[1]) / MINIMAP_SCALE)
        following = False

    keys = pygame.key.get_pressed()
    move_x = move_y = 0
    if keys[pygame.K_LEFT] or keys[pygame.K_a]:
        move_x -= SCROLL_SPEED
    if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
        move_x += SCROLL_SPEED
    if keys[pygame.K_UP] or keys[pygame.K_w]:
        move_y -= SCROLL_SPEED
    if keys[pygame.K_DOWN] or keys[pygame.K_s]:
        move_y += SCROLL_SPEED
    if move_x or move_y:
        camera.move(move_x, move_y)
        following = False
    if keys[pygame.K_EQUALS] or keys[pygame.K_KP_PLUS] or keys[pygame.K_e]:
        camera.zoom_at(MAP_WIDTH / 2, HEIGHT / 2, KEY_ZOOM)
    if keys[pygame.K_MINUS] or keys[pygame.K_KP_MINUS] or keys[pygame.K_q]:
        camera.zoom_at(MAP_WIDTH / 2, HEIGHT / 2, 1 / KEY_ZOOM)

    # Run the city: 0 steps when paused, more steps per frame when fast-forwarding
    steps = 0 if paused else SPEEDS[speed_index]
    for _ in range(steps):
        simulate_one_step(frame)
        frame += 1

    if following and selected is not None:
        camera.center_on(selected.x, selected.y)

    sim_minutes = START_HOUR * 60 + frame / FPS
    hour = int(sim_minutes // 60) % 24

    draw_world_view(background)
    draw_night((sim_minutes / 60) % 24)
    for bus in Bus.fleet:
        bus.draw_bay(screen)
    for stop in ALL_STOPS:
        stop.draw(screen, frame)
    for light in LIGHTS:
        light.draw(screen, frame)
    for bus in Bus.fleet:
        bus.draw(screen, frame)
    draw_selection()
    if show_help:
        draw_help()
    if show_stats:
        draw_stats()
    if toast and pygame.time.get_ticks() < toast_until:
        message = get_font(16).render(toast, True, BLACK)
        box = message.get_rect(midbottom=(MAP_WIDTH // 2, HEIGHT - 20)).inflate(24, 14)
        pygame.draw.rect(screen, LIGHT_COLORS["green"], box, border_radius=8)
        screen.blit(message, message.get_rect(center=box.center))
    draw_panel(sim_minutes, demand_multiplier(hour), minimap)

    pygame.display.flip()
    clock.tick(FPS)

pygame.quit()
