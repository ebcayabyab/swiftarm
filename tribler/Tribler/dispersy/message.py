from member import DummyMember
from meta import MetaObject

if __debug__:
    import re
    from dprint import dprint

#
# Exceptions
#
class DelayPacket(Exception):
    """
    Uses an identifier to match request to response.
    """
    def __init__(self, msg, community):
        super(DelayPacket, self).__init__(msg)
        self._community = community

    def create_request(self, candidate, delayed):
        # create and send a request.  once the response is received the _process_delayed_packet can
        # pass the (candidate, delayed) tuple to dispersy for reprocessing
        raise NotImplementedError()

    def _process_delayed_packet(self, response, candidate, delayed):
        if response:
            # process the response and the delayed message
            self._community.dispersy.on_incoming_packets([(candidate, delayed)])

        else:
            # timeout, do nothing
            pass

class DelayPacketByMissingMember(DelayPacket):
    def __init__(self, community, missing_member_id):
        assert isinstance(missing_member_id, str)
        assert len(missing_member_id) == 20
        super(DelayPacketByMissingMember, self).__init__("Missing member", community)
        self._missing_member_id = missing_member_id

    def create_request(self, candidate, delayed):
        self._community.dispersy.create_missing_identity(self._community, candidate, DummyMember(self._missing_member_id), self._process_delayed_packet, (candidate, delayed))

class DelayPacketByMissingLastMessage(DelayPacket):
    def __init__(self, community, member, message, count):
        if __debug__:
            from member import Member
        assert isinstance(member, Member)
        assert isinstance(message, Message)
        assert isinstance(count, int)
        super(DelayPacketByMissingLastMessage, self).__init__("Missing last message", community)
        self._member = member
        self._message = message
        self._count = count

    def create_request(self, candidate, delayed):
        self._community.dispersy.create_missing_last_message(self._community, candidate, self._member, self._message, self._count, self._process_delayed_packet, (candidate, delayed))

class DelayPacketByMissingMessage(DelayPacket):
    def __init__(self, community, member, global_time):
        if __debug__:
            from community import Community
            from member import Member
        assert isinstance(community, Community)
        assert isinstance(member, Member)
        assert isinstance(global_time, (int, long))
        super(DelayPacketByMissingMessage, self).__init__("Missing message (new style)", community)
        self._member = member
        self._global_time = global_time

    def create_request(self, candidate, delayed):
        self._community.dispersy.create_missing_message(self._community, candidate, self._member, self._global_time, self._process_delayed_packet, (candidate, delayed))

class DropPacket(Exception):
    """
    Raised by Conversion.decode_message when the packet is invalid.
    I.e. does not conform to valid syntax, contains malicious
    behaviour, etc.
    """
    pass

class DelayMessage(Exception):
    """
    Uses an identifier to match request to response.

    Ensure to call Dispersy.handle_missing_messages for each incoming message that may have been
    requested.
    """
    def __init__(self, delayed):
        if __debug__:
            from message import Message
        assert isinstance(delayed, Message.Implementation)
        super(DelayMessage, self).__init__("delay")
        self._delayed = delayed

    @property
    def delayed(self):
        return self._delayed

    def create_request(self):
        # create and send a request.  once the response is received the _process_delayed_message can
        # pass the (candidate, delayed) tuple to dispersy for reprocessing
        raise NotImplementedError()

    def _process_delayed_message(self, response):
        if response:
            # process the response and the delayed message
            self._delayed.community.dispersy.on_messages([self._delayed])

        else:
            # timeout, do nothing
            pass

class DelayMessageByProof(DelayMessage):
    def create_request(self):
        community = self._delayed.community
        community.dispersy.create_missing_proof(community, self._delayed.candidate, self._delayed, self._process_delayed_message)

class DelayMessageBySequence(DelayMessage):
    def __init__(self, delayed, missing_low, missing_high):
        assert isinstance(missing_low, (int, long))
        assert isinstance(missing_high, (int, long))
        assert 0 < missing_low <= missing_high
        super(DelayMessageBySequence, self).__init__(delayed)
        self._missing_low = missing_low
        self._missing_high = missing_high

    def create_request(self):
        community = self._delayed.community
        community.dispersy.create_missing_sequence(community, self._delayed.candidate, self._delayed.authentication.member, self._delayed.meta, self._missing_low, self._missing_high, self._process_delayed_message)

class DelayMessageBySubjectiveSet(DelayMessage):
    def __init__(self, delayed, cluster):
        assert isinstance(cluster, int)
        super(DelayMessageBySubjectiveSet, self).__init__(delayed)
        self._cluster = cluster

    def create_request(self):
        community = self._delayed.community
        community.dispersy.create_missing_subjective_set(community, self._delayed.candidate, self._delayed.authentication.member, self._cluster, self._process_delayed_message)

class DropMessage(Exception):
    """
    Raised during Community.on_message.

    Drops a message because it violates 'something'.  More specific
    reasons can be given with by raising a spectific subclass.
    """
    def __init__(self, dropped, msg):
        if __debug__:
            from message import Message
        assert isinstance(dropped, Message.Implementation)
        assert isinstance(msg, (str, unicode))
        self._dropped = dropped
        super(DropMessage, self).__init__(msg)

    @property
    def dropped(self):
        return self._dropped

#
# batch
#

class BatchConfiguration(object):
    def __init__(self, max_window=0.0, priority=128, max_size=1024, max_age=300.0):
        """
        Per meta message configuration on batch handling.

        MAX_WINDOW sets the maximum size, in seconds, of the window.  A larger window results in
        larger batches and a longer average delay for incoming messages.  Setting MAX_WINDOW to zero
        disables batching, in this case all other parameters are ignored.

        PRIORITY sets the Callback priority of the task that processes the batch.  A higher priority
        will result in earlier handling when there is CPU contention.

        MAX_SIZE sets the maximum size of the batch.  A new batch will be created when this size is
        reached, even when new messages would fall within MAX_WINDOW size.  A larger MAX_SIZE
        results in more processing time per batch and will reduce responsiveness as the processing
        thread is occupied.  Also, when a batch reaches MAX_SIZE it is processed immediately.

        MAX_AGE sets the maximum age of the batch.  This is useful for messages that require a
        response.  When the requests are delayed for to long they will time out, in this case a
        response no longer needs to be sent.  MAX_AGE for the request messages should hence be lower
        than the used timeout + max_window on the response messages.
        """
        assert isinstance(max_window, float)
        assert 0.0 <= max_window, max_window
        assert isinstance(priority, int)
        assert isinstance(max_size, int)
        assert 0 < max_size, max_size
        assert isinstance(max_age, float)
        assert 0.0 <= max_window < max_age, [max_window, max_age]
        self._max_window = max_window
        self._priority = priority
        self._max_size = max_size
        self._max_age = max_age

    @property
    def enabled(self):
        # enabled when max_window is positive
        return 0.0 < self._max_window

    @property
    def max_window(self):
        return self._max_window

    @property
    def priority(self):
        return self._priority

    @property
    def max_size(self):
        return self._max_size

    @property
    def max_age(self):
        return self._max_age

#
# packet
#

class Packet(MetaObject.Implementation):
    def __init__(self, meta, packet, packet_id):
        assert isinstance(packet, str)
        assert isinstance(packet_id, (int, long))
        super(Packet, self).__init__(meta)
        self._packet = packet
        self._packet_id = packet_id

    @property
    def community(self):
        return self._meta._community

    @property
    def name(self):
        return self._meta._name

    @property
    def database_id(self):
        return self._meta._database_id

    @property
    def resolution(self):
        return self._meta._resolution

    @property
    def check_callback(self):
        return self._meta._check_callback

    @property
    def handle_callback(self):
        return self._meta._handle_callback

    @property
    def undo_callback(self):
        return self._meta._undo_callback

    @property
    def priority(self):
        return self._meta._priority

    @property
    def delay(self):
        return self._meta._delay

    @property
    def packet(self):
        return self._packet

    # @property
    def __get_packet_id(self):
        return self._packet_id
    # @packet_id.setter
    def __set_packet_id(self, packet_id):
        assert isinstance(packet_id, (int, long))
        self._packet_id = packet_id
    # .setter was introduced in Python 2.6
    packet_id = property(__get_packet_id, __set_packet_id)

    def load_message(self):
        message = self._meta.community.dispersy.convert_packet_to_message(self._packet, self._meta.community, verify=False)
        message.packet_id = self._packet_id
        return message

    def __str__(self):
        return "<%s.%s %s %dbytes>" % (self._meta.__class__.__name__, self.__class__.__name__, self._meta._name, len(self._packet))

#
# message
#
class Message(MetaObject):
    class Implementation(Packet):
        def __init__(self, meta, authentication, resolution, distribution, destination, payload, conversion=None, candidate=None, packet="", packet_id=0):
            if __debug__:
                from payload import Payload
                from conversion import Conversion
                from candidate import Candidate
            assert isinstance(meta, Message), "META has invalid type '%s'" % type(meta)
            assert isinstance(authentication, meta._authentication.Implementation), "AUTHENTICATION has invalid type '%s'" % type(authentication)
            assert isinstance(resolution, meta._resolution.Implementation), "RESOLUTION has invalid type '%s'" % type(resolution)
            assert isinstance(distribution, meta._distribution.Implementation), "DISTRIBUTION has invalid type '%s'" % type(distribution)
            assert isinstance(destination, meta._destination.Implementation), "DESTINATION has invalid type '%s'" % type(destination)
            assert isinstance(payload, meta._payload.Implementation), "PAYLOAD has invalid type '%s'" % type(payload)
            assert conversion is None or isinstance(conversion, Conversion), "CONVERSION has invalid type '%s'" % type(conversion)
            assert candidate is None or isinstance(candidate, Candidate)
            assert isinstance(packet, str)
            assert isinstance(packet_id, (int, long))
            super(Message.Implementation, self).__init__(meta, packet, packet_id)
            self._authentication = authentication
            self._resolution = resolution
            self._distribution = distribution
            self._destination = destination
            self._payload = payload
            self._candidate = candidate

            # allow setup parts.  used to setup callback when something changes that requires the
            # self._packet to be generated again
            self._authentication.setup(self)
            # self._resolution.setup(self)
            # self._distribution.setup(self)
            # self._destination.setup(self)
            # self._payload.setup(self)

            if conversion:
                self._conversion = conversion
            elif packet:
                self._conversion = meta._community.get_conversion(packet[:22])
            else:
                self._conversion = meta._community.get_conversion()

            if not packet:
                self._packet = self._conversion.encode_message(self)

        @property
        def conversion(self):
            return self._conversion

        @property
        def authentication(self):
            return self._authentication

        @property
        def resolution(self):
            return self._resolution

        @property
        def distribution(self):
            return self._distribution

        @property
        def destination(self):
            return self._destination

        @property
        def payload(self):
            return self._payload

        @property
        def candidate(self):
            return self._candidate

        def load_message(self):
            return self

        def regenerate_packet(self, packet=""):
            if packet:
                self._packet = packet
            else:
                self._packet = self._conversion.encode_message(self)

        def __str__(self):
            return "<%s.%s %s %dbytes>" % (self._meta.__class__.__name__, self.__class__.__name__, self._meta._name, len(self._packet))

    def __init__(self, community, name, authentication, resolution, distribution, destination, payload, check_callback, handle_callback, undo_callback=None, batch=None):
        if __debug__:
            from community import Community
            from authentication import Authentication
            from resolution import Resolution, DynamicResolution
            from destination import Destination
            from distribution import Distribution
            from payload import Payload
        assert isinstance(community, Community), "COMMUNITY has invalid type '%s'" % type(community)
        assert isinstance(name, unicode), "NAME has invalid type '%s'" % type(name)
        assert isinstance(authentication, Authentication), "AUTHENTICATION has invalid type '%s'" % type(authentication)
        assert isinstance(resolution, Resolution), "RESOLUTION has invalid type '%s'" % type(resolution)
        assert isinstance(distribution, Distribution), "DISTRIBUTION has invalid type '%s'" % type(distribution)
        assert isinstance(destination, Destination), "DESTINATION has invalid type '%s'" % type(destination)
        assert isinstance(payload, Payload), "PAYLOAD has invalid type '%s'" % type(payload)
        assert callable(check_callback)
        assert callable(handle_callback)
        assert undo_callback is None or callable(undo_callback), undo_callback
        if __debug__:
            if isinstance(resolution, DynamicResolution):
                assert callable(undo_callback), "UNDO_CALLBACK must be specified when using the DynamicResolution policy"
        assert batch is None or isinstance(batch, BatchConfiguration)
        assert self.check_policy_combination(authentication, resolution, distribution, destination)
        self._community = community
        self._name = name
        self._authentication = authentication
        self._resolution = resolution
        self._distribution = distribution
        self._destination = destination
        self._payload = payload
        self._check_callback = check_callback
        self._handle_callback = handle_callback
        self._undo_callback = undo_callback
        self._batch = BatchConfiguration() if batch is None else batch

        # use cache to avoid database queries
        cache = community.meta_message_cache.get(name)
        if cache:
            self._database_id = cache["id"]
        else:
            # ensure that there is a database id associated to this meta message name
            community.dispersy.database.execute(u"INSERT INTO meta_message (community, name, cluster, priority, direction) VALUES (?, ?, 0, 128, 1)",
                                                (community.database_id, name))
            self._database_id = community.dispersy.database.last_insert_rowid
            community.meta_message_cache[name] = {"id":self._database_id, "cluster":0, "priority":128, "direction":1}

        # allow optional setup methods to initialize the specific parts of the meta message
        self._authentication.setup(self)
        self._resolution.setup(self)
        self._distribution.setup(self)
        self._destination.setup(self)
        self._payload.setup(self)

    @property
    def community(self):
        return self._community

    @property
    def name(self):
        return self._name

    @property
    def database_id(self):
        return self._database_id

    @property
    def authentication(self):
        return self._authentication

    @property
    def resolution(self):
        return self._resolution

    @property
    def distribution(self):
        return self._distribution

    @property
    def destination(self):
        return self._destination

    @property
    def payload(self):
        return self._payload

    @property
    def check_callback(self):
        return self._check_callback

    @property
    def handle_callback(self):
        return self._handle_callback

    @property
    def undo_callback(self):
        return self._undo_callback

    @property
    def batch(self):
        return self._batch

    def impl(self, authentication=(), resolution=(), distribution=(), destination=(), payload=(), *args, **kargs):
        if __debug__:
            assert isinstance(authentication, tuple), type(authentication)
            assert isinstance(resolution, tuple), type(resolution)
            assert isinstance(distribution, tuple), type(distribution)
            assert isinstance(destination, tuple), type(destination)
            assert isinstance(payload, tuple), type(payload)
            try:
                authentication_impl = self._authentication.Implementation(self._authentication, *authentication)
                resolution_impl = self._resolution.Implementation(self._resolution, *resolution)
                distribution_impl = self._distribution.Implementation(self._distribution, *distribution)
                destination_impl = self._destination.Implementation(self._destination, *destination)
                payload_impl = self._payload.Implementation(self._payload, *payload)
            except TypeError:
                dprint("message name:   ", self._name, level="error")
                dprint("authentication: ", self._authentication.__class__.__name__, ".Implementation", level="error")
                dprint("resolution:     ", self._resolution.__class__.__name__, ".Implementation", level="error")
                dprint("distribution:   ", self._distribution.__class__.__name__, ".Implementation", level="error")
                dprint("destination:    ", self._destination.__class__.__name__, ".Implementation", level="error")
                dprint("payload:        ", self._payload.__class__.__name__, ".Implementation", level="error")
                raise
            else:
                return self.Implementation(self, authentication_impl, resolution_impl, distribution_impl, destination_impl, payload_impl, *args, **kargs)

        return self.Implementation(self,
                                   self._authentication.Implementation(self._authentication, *authentication),
                                   self._resolution.Implementation(self._resolution, *resolution),
                                   self._distribution.Implementation(self._distribution, *distribution),
                                   self._destination.Implementation(self._destination, *destination),
                                   self._payload.Implementation(self._payload, *payload),
                                   *args, **kargs)


    def __str__(self):
        return "<%s %s>" % (self.__class__.__name__, self._name)

    @staticmethod
    def check_policy_combination(authentication, resolution, distribution, destination):
        from authentication import Authentication, NoAuthentication, MemberAuthentication, MultiMemberAuthentication
        from resolution import Resolution, PublicResolution, LinearResolution, DynamicResolution
        from distribution import Distribution, RelayDistribution, DirectDistribution, FullSyncDistribution, LastSyncDistribution
        from destination import Destination, CandidateDestination, MemberDestination, CommunityDestination, SubjectiveDestination

        assert isinstance(authentication, Authentication)
        assert isinstance(resolution, Resolution)
        assert isinstance(distribution, Distribution)
        assert isinstance(destination, Destination)

        def require(a, b, c):
            if not isinstance(b, c):
                raise ValueError("%s does not support %s.  Allowed options are: %s" % (a.__class__.__name__, b.__class__.__name__, ", ".join([x.__name__ for x in c])))

        if isinstance(authentication, NoAuthentication):
            require(authentication, resolution, PublicResolution)
            require(authentication, distribution, (RelayDistribution, DirectDistribution))
            require(authentication, destination, (CandidateDestination, MemberDestination, CommunityDestination))
        elif isinstance(authentication, MemberAuthentication):
            require(authentication, resolution, (PublicResolution, LinearResolution, DynamicResolution))
            require(authentication, distribution, (RelayDistribution, DirectDistribution, FullSyncDistribution, LastSyncDistribution))
            require(authentication, destination, (CandidateDestination, MemberDestination, CommunityDestination, SubjectiveDestination))
        elif isinstance(authentication, MultiMemberAuthentication):
            require(authentication, resolution, (PublicResolution, LinearResolution, DynamicResolution))
            require(authentication, distribution, (RelayDistribution, DirectDistribution, FullSyncDistribution, LastSyncDistribution))
            require(authentication, destination, (CandidateDestination, MemberDestination, CommunityDestination, SubjectiveDestination))
        else:
            raise ValueError("%s is not supported" % authentication.__class_.__name__)

        if isinstance(resolution, PublicResolution):
            require(resolution, authentication, (NoAuthentication, MemberAuthentication, MultiMemberAuthentication))
            require(resolution, distribution, (RelayDistribution, DirectDistribution, FullSyncDistribution, LastSyncDistribution))
            require(resolution, destination, (CandidateDestination, MemberDestination, CommunityDestination, SubjectiveDestination))
        elif isinstance(resolution, LinearResolution):
            require(resolution, authentication, (MemberAuthentication, MultiMemberAuthentication))
            require(resolution, distribution, (RelayDistribution, DirectDistribution, FullSyncDistribution, LastSyncDistribution))
            require(resolution, destination, (CandidateDestination, MemberDestination, CommunityDestination, SubjectiveDestination))
        elif isinstance(resolution, DynamicResolution):
            pass
        else:
            raise ValueError("%s is not supported" % resolution.__class_.__name__)

        if isinstance(distribution, RelayDistribution):
            require(distribution, authentication, (NoAuthentication, MemberAuthentication, MultiMemberAuthentication))
            require(distribution, resolution, (PublicResolution, LinearResolution, DynamicResolution))
            require(distribution, destination, (CandidateDestination, MemberDestination))
        elif isinstance(distribution, DirectDistribution):
            require(distribution, authentication, (NoAuthentication, MemberAuthentication, MultiMemberAuthentication))
            require(distribution, resolution, (PublicResolution, LinearResolution, DynamicResolution))
            require(distribution, destination, (CandidateDestination, MemberDestination, CommunityDestination))
        elif isinstance(distribution, FullSyncDistribution):
            require(distribution, authentication, (MemberAuthentication, MultiMemberAuthentication))
            require(distribution, resolution, (PublicResolution, LinearResolution, DynamicResolution))
            require(distribution, destination, (CommunityDestination, SubjectiveDestination))
            if isinstance(authentication, MultiMemberAuthentication) and distribution.enable_sequence_number:
                raise ValueError("%s may not be used with %s when sequence numbers are enabled" % (distribution.__class__.__name__, authentication.__class__.__name__))
        elif isinstance(distribution, LastSyncDistribution):
            require(distribution, authentication, (MemberAuthentication, MultiMemberAuthentication))
            require(distribution, resolution, (PublicResolution, LinearResolution, DynamicResolution))
            require(distribution, destination, (CommunityDestination, SubjectiveDestination))
        else:
            raise ValueError("%s is not supported" % distribution.__class_.__name__)

        if isinstance(destination, CandidateDestination):
            require(destination, authentication, (NoAuthentication, MemberAuthentication, MultiMemberAuthentication))
            require(destination, resolution, (PublicResolution, LinearResolution, DynamicResolution))
            require(destination, distribution, (RelayDistribution, DirectDistribution))
        elif isinstance(destination, MemberDestination):
            require(destination, authentication, (NoAuthentication, MemberAuthentication, MultiMemberAuthentication))
            require(destination, resolution, (PublicResolution, LinearResolution, DynamicResolution))
            require(destination, distribution, (RelayDistribution, DirectDistribution))
        elif isinstance(destination, CommunityDestination):
            require(destination, authentication, (NoAuthentication, MemberAuthentication, MultiMemberAuthentication))
            require(destination, resolution, (PublicResolution, LinearResolution, DynamicResolution))
            require(destination, distribution, (DirectDistribution, FullSyncDistribution, LastSyncDistribution))
        elif isinstance(destination, SubjectiveDestination):
            require(destination, authentication, (MemberAuthentication, MultiMemberAuthentication))
            require(destination, resolution, (PublicResolution, LinearResolution, DynamicResolution))
            require(destination, distribution, (FullSyncDistribution, LastSyncDistribution))
        else:
            raise ValueError("%s is not supported" % destination.__class_.__name__)

        return True
