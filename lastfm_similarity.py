# -*- coding: utf-8 -*-
import json
import urllib2

from gi.repository import GLib

from quodlibet import _
from quodlibet import app
from quodlibet.plugins.events import EventPlugin
from quodlibet.plugins import PluginConfig
from quodlibet.qltk import Icons
from quodlibet.query import Query
from quodlibet.util.dprint import print_d


pconfig = PluginConfig("notify")
pconfig.defaults.set("blacklist_track_count", 10)
pconfig.defaults.set("blacklist_artist_count", 10)


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
        self._last_tracks = []
        self._last_artists = []

    def _check_artist_played(self, artist):
        if artist in self._last_artists:
            return True
        else:
            return False

    def _check_track_played(self, track):
        if track in self._last_tracks:
            return True
        else:
            return False

    def _build_uri(self, request):
        return "".join((self.LAST_FM_API_URI, request, "&api_key=",
                        self.API_KEY, "&format=json"))

    def _find_similar_tracks(self, trackname, artistname, mbid=None, limit=20):
        request = "".join(("?method=",
                           self.LAST_FM_API_METHODS["similar_tracks"]))

        if mbid:
            request = "".join((request, "&mbid=", mbid))
        else:
            request = "".join((request, "&track=", trackname, "&artist=",
                               artistname))

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
                return []

        else:
            return []

    def _find_similar_artists(self, artistname, mbid=None, limit=20):
        request = "".join(("?method=",
                           self.LAST_FM_API_METHODS["similar_artists"]))

        if mbid:
            request = "".join((request, "&mbid=", mbid))
        else:
            request = "".join((request, "&artist=", artistname))

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
                return []

        else:
            return []

    def on_change(self, song):
        artist = song.get("artist")
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

                    if (len(self._last_tracks)
                            == pconfig.getint("blacklist_track_count")):
                        del self._last_tracks[0]

                    query = Query.StrictQueryMatcher(
                        "&(artist = \"%s\", title = \"%s\")"
                        % (candidate[0], candidate[1]))
                    try:
                        results = filter(query.search, app.library)

                        if results:
                            song = results[0]

                            if self._check_track_played(song.get("~filename")):
                                continue

                            self._last_tracks.append(song.get("~filename"))

                            if (len(self._last_artists)
                                    == pconfig.getint(
                                        "blacklist_artist_count")):
                                del self._last_artists[0]

                            self._last_artists.append(song.get("artist"))

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

                    for song in results:
                        if self._check_track_played(song.get("~filename")):
                            continue

                        if (len(self._last_artists)
                                == pconfig.getint("blacklist_artist_count")):
                            del self._last_artists[0]

                        self._last_artists.append(song.get("artist"))
                        self._last_tracks.append(song.get("~filename"))

                        app.window.playlist.enqueue([song])
                        return
                except AttributeError:
                    pass

    def plugin_on_song_started(self, song):
        self._last_tracks.append(song.get("~filename"))
        self._last_artists.append(song.get("artist"))

        GLib.idle_add(self.on_change, song)

    def plugin_on_song_ended(self, song, stopped):

        if len(self._last_tracks) == pconfig.getint("blacklist_track_count"):
            del self._last_tracks[0]

        if len(self._last_artists) == pconfig.getint("blacklist_artist_count"):
            del self._last_artists[0]
