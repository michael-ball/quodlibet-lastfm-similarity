# -*- coding: utf-8 -*-
import json
import urllib2
import random

from gi.repository import GLib, Gtk

from quodlibet import _, app, config
from quodlibet.plugins.events import EventPlugin
from quodlibet.qltk import Icons
from quodlibet.query import Query
from quodlibet.util.dprint import print_d


class LastFMSimilarity(EventPlugin):
    PLUGIN_ID = "Last.fm Similarity"
    PLUGIN_NAME = _("Last.fm Similarity")
    PLUGIN_DESC = _("Finds a similar song using Last.fm's track similarity API"
                    " and adds it to the queue.")
    PLUGIN_ICON = Icons.NETWORK_WORKGROUP

    LAST_FM_API_URI = "http://ws.audioscrobbler.com/2.0/"
    API_KEY = "e94b09aa2c04ab264deb7a7ae02ecd05"

    LAST_FM_API_METHODS = {
        "similar_artists": "artist.getSimilar",
        "similar_tracks": "track.getSimilar",
    }

    def __init__(self):
        self._blacklist_track_count = config.getint("plugins", "lastfm_similarity_blacklist_tracks", 10)
        self._blacklist_artist_count = config.getint("plugins", "lastfm_similarity_blacklist_artists", 10)
        self._last_tracks = []
        self._last_artists = []


    def PluginPreferences(self, parent):
        def blacklist_track_changed(entry):
            self._blacklist_track_count = int(entry.get_value())
            config.set("plugins", "lastfm_similarity_blacklist_tracks", self._blacklist_track_count)

        def blacklist_artist_changed(entry):
            self._blacklist_artist_count = int(entry.get_value())
            config.set("plugins", "lastfm_similarity_blacklist_artist", self._blacklist_artist_count)

        table = Gtk.Table(rows=2, columns=2)
        table.set_row_spacings(6)
        table.set_col_spacings(6)
        table.attach(Gtk.Label(label=_("Number of recently played tracks to blacklist:")), 0, 1, 0, 1)
        track_entry = Gtk.SpinButton(adjustment=Gtk.Adjustment.new(self._blacklist_track_count, 0, 1000, 1, 10, 0))
        track_entry.connect("value-changed", blacklist_track_changed)
        table.attach(track_entry, 1, 2, 0, 1)
        table.attach(Gtk.Label(label=_("Number of recently played artists to blacklist:")), 0, 1, 1, 2)
        artist_entry = Gtk.SpinButton(adjustment=Gtk.Adjustment.new(self._blacklist_artist_count, 0, 1000, 1, 10, 0))
        artist_entry.connect("value-changed", blacklist_artist_changed)
        table.attach(artist_entry, 1, 2, 1, 2)
        return table

    def _check_artist_played(self, artist):
        for played_artist in self._last_artists:
            if unicode(artist).upper() == played_artist.upper():
                return True

        return False

    def _check_track_played(self, track):
        if track in self._last_tracks:
            return True
        else:
            return False

    def _add_played_artists(self, artists):
        for artist in artists:
            if artist not in self._last_artists:
                self._last_artists.append(artist)

    def _build_uri(self, request):
        return "".join((self.LAST_FM_API_URI, request, "&api_key=",
                        self.API_KEY, "&format=json"))

    def _find_similar_tracks(self, trackname, artistname, mbid=None, limit=50):
        request = "".join(("?method=",
                           self.LAST_FM_API_METHODS["similar_tracks"]))

        if mbid:
            print_d("Trying with mbid {}".format(mbid))
            request = "".join((request, "&mbid=", mbid))
        else:
            print_d("Trying with {} - {}".format(artistname.splitlines()[0],
                                                 trackname))
            request = "".join((request, "&track=", trackname, "&artist=",
                               artistname.splitlines()[0]))

        request = "".join((request, "&limit={}".format(limit)))

        uri = self._build_uri(request)

        stream = None

        try:
            stream = urllib2.urlopen(uri)
        except urllib2.URLError:
            return []

        if stream.getcode() == 200:
            similar_tracks = []

            try:
                response = json.load(stream)

                for track in response["similartracks"]["track"]:
                    similar_tracks.append(
                        (track["artist"]["name"], track["name"]))

                return similar_tracks

            except KeyError:
                if mbid:
                    return self._find_similar_tracks(trackname, artistname)

                return []

        else:
            return []

    def _find_similar_artists(self, artistname, mbid=None, limit=40):
        request = "".join(("?method=",
                           self.LAST_FM_API_METHODS["similar_artists"]))

        if mbid:
            print_d("Trying with artist mbid {}".format(mbid))
            request = "".join((request, "&mbid=", mbid))
        else:
            print_d("Trying with {}".format(artistname.splitlines()[0]))
            request = "".join((request, "&artist=",
                               artistname.splitlines()[0]))

        request = "".join((request, "&limit={}".format(limit)))

        uri = self._build_uri(request)

        stream = None

        try:
            stream = urllib2.urlopen(uri)
        except urllib2.URLError:
            return []

        if stream.getcode() == 200:
            similar_artists = []

            try:
                response = json.load(stream)

                for artist in response["similarartists"]["artist"]:
                    similar_artists.append(artist["name"])

                return similar_artists

            except KeyError:
                if mbid:
                    return self._find_similar_artists(artistname)

                return []

        else:
            return []

    def on_change(self, song):
        artist = song.get("artist").splitlines()[0]
        track = song.get("title")

        candidates = []

        try:
            mbid = song.get("musicbrainz_releasetrackid")

            candidates = self._find_similar_tracks(track, artist, mbid)
        except KeyError:
            candidates = self._find_similar_tracks(track, artist)

        if candidates:
            for candidate in candidates:
                if not self._check_artist_played(candidate[0]):

                    print_d("[similarity] found track match: %s - %s"
                            % (candidate[0], candidate[1]))

                    query = Query.StrictQueryMatcher(
                        "&(artist = \"%s\", title = \"%s\")"
                        % (candidate[0], candidate[1]))
                    try:
                        results = filter(query.search, app.library)

                        if results:
                            song = results[0]

                            if self._check_track_played(song.get("~filename")):
                                continue

                            app.window.playlist.enqueue([song])

                            return
                    except AttributeError:
                        pass

        artist_candidates = self._find_similar_artists(artist)

        for artist in artist_candidates:
            if not self._check_artist_played(artist):
                print_d("[similarity] found artist match: %s" % artist)

                query = Query.StrictQueryMatcher(
                    "&(artist = \"%s\", title != \"[silence]\")" % artist)
                try:
                    results = filter(query.search, app.library)

                    candidate_song_length = len(results)
                    for dummy in xrange(candidate_song_length):
                        idx = random.randint(0, (candidate_song_length - 1))
                        song = results[idx]

                        if not self._check_track_played(song.get("~filename")):
                            app.window.playlist.enqueue([song])
                            return

                except AttributeError:
                    pass

    def plugin_on_song_started(self, song):
        self._last_tracks.append(song.get("~filename"))
        self._add_played_artists(song.get("artist").splitlines())

        GLib.idle_add(self.on_change, song)

    def plugin_on_song_ended(self, song, stopped):

        track_count = len(self._last_tracks)
        artist_count = len(self._last_artists)

        if track_count > self._blacklist_track_count:
            self._last_tracks = self._last_tracks[
                (track_count - self._blacklist_track_count):track_count]

        if artist_count > self._blacklist_artist_count:
            self._last_artists = self._last_artists[
                (artist_count - self._blacklist_artist_count):artist_count]
