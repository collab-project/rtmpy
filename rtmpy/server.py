# Copyright (c) The RTMPy Project.
# See LICENSE.txt for details.

"""
Server implementation.
"""

from zope.interface import Interface, Attribute, implements
from twisted.internet import protocol, defer, reactor
import pyamf

from rtmpy import util
from rtmpy.protocol import rtmp, handshake, version


class NetConnectionError(Exception):
    """
    """


class ConnectError(NetConnectionError):
    """
    """


class ConnectFailed(ConnectError):
    """
    """

    code = 'NetConnection.Connect.Failed'


class ServerControlStream(rtmp.ControlStream):
    """
    """

    def _handleInvokeResponse(self, result, id_):
        return result

    def onInvoke(self, name, id_, args, timestamp):
        """
        """
        if self.application is None:
            if name == 'connect':
                d = self.activeInvokes[id_] = defer.maybeDeferred(
                    self.protocol.onConnect, args[0])

                d.addBoth(self._handleInvokeResponse, id_)

                return d

        rtmp.ControlStream.onInvoke(self, name, id_, args, timestamp)


class OldServerControlStream(object):
    """
    """

    def _fatal(self, f):
        """
        If we ever get here then a pathological error occurred and the only
        thing left to do is to log the error and kill the connection.

        Only to be used as part of a deferred call/errback chain.
        """
        self.protocol.logAndDisconnect(f)

    def onInvoke(self, invoke):
        """
        """
        d = None

        def cb(res):
            if not isinstance(res, (tuple, list)):
                res = (None, res)

            s = res[1]

            if isinstance(s, status.Status):
                if s.level == 'error':
                    return event.Invoke('_error', invoke.id, *res)

            return event.Invoke('_result', invoke.id, *res)

        if invoke.name == u'connect':
            def eb(f):
                # TODO: log the error
                print f
                return status.error(
                    code='NetConnection.Connect.Failed',
                    description='Internal Server Error'
                )

            def check_error(res):
                if not isinstance(res, event.Invoke):
                    return res

                if res.name == '_error':
                    self.writeEvent(res, channelId=2)
                    self.writeEvent(event.Invoke('close', 0, None), channelId=2)

                    return

                return res

            d = defer.maybeDeferred(self.protocol.onConnect, *invoke.argv)
            d.addErrback(eb).addCallback(cb).addCallback(check_error)
        elif invoke.name == u'createStream':
            d = defer.maybeDeferred(self.protocol.createStream)

            d.addCallback(cb)
        elif invoke.name == u'deleteStream':
            d = defer.maybeDeferred(self.protocol.removeStream, *invoke.argv[1:])

            d.addCallback(cb).addCallback(lambda _: None)
        else:
            def eb(f):
                # TODO: log the error
                print f
                return status.error(
                    code='NetConnection.Call.Failed',
                    description='Internal Server Error'
                )

            kls = self.protocol.client.__class__

            if not hasattr(kls, invoke.name):
                return status.error(
                    code='NetConnection.Call.Failed',
                    description="Unknown method '%s'" % (invoke.name,)
                )

            method = getattr(self.protocol.client, invoke.name)

            d = defer.maybeDeferred(method, *invoke.argv[1:])

            d.addErrback(eb).addCallback(cb)

        return d.addErrback(self._fatal)

    def onDownstreamBandwidth(self, bandwidth):
        """
        """
        self.protocol.onDownstreamBandwidth(bandwidth)

    def onFrameSize(self, size):
        self.protocol.decoder.setFrameSize(size)


class IApplication(Interface):
    """
    """

    clients = Attribute("A collection of clients connected to this application.")
    name = Attribute("The name of the application instance.")
    factory = Attribute("The Factory instance that this application is"
        "attached to.")

    def startup():
        """
        Called when the server loads the application instance. Can return a
        deferred that signals that the application has fully initialized.
        """

    def shutdown():
        """
        Called when the application is unloaded. Can return a deferred that
        signals that the application has completely shutdown. Use this to
        close database connections etc.
        """

    def rejectConnection(client, reason):
        """
        Rejects the connection from the client, C{reason} being a
        L{failure.Failure} object or a string. Once the client has been
        rejected, the connection to the client must be closed.
        """

    def acceptConnection(client):
        """
        Called when the client connection request has been accepted by this
        application.
        """

    def disconnect(client, reason=None):
        """
        Disconnects a client from the application. Returns a deferred that is
        called when the disconnection was successful.
        """


class Client(object):
    """
    """

    def __init__(self):
        self.protocol = None
        self.application = None

        self.pendingCalls = []

    def call(self, name, *args):
        """
        """
        d = defer.Deferred()

        if args == ():
            args = (None,)

        if self.application is None:
            self.pendingCalls.append((name, args, d))

            return d

        s = self.protocol.getStream(0)
        x = s.writeEvent(event.Invoke(name, 0, *args), channelId=3)

        x.addCallback(lambda _: d.callback(pyamf.Undefined))

        return d

    def registerApplication(self, application):
        """
        """
        self.application = application
        s = self.protocol.getStream(0)

        for name, args, d in self.pendingCalls:
            x = s.writeEvent(event.Invoke(name, 0, *args), channelId=3)

            x.chainDeferred(d)

        self.pendingCalls = []

    def disconnect(self):
        """
        Disconnects the client. Returns a deferred to signal when this client
        has disconnected.
        """
        def cb(_):
            self.application.onDisconnect(self)
            self.protocol.transport.loseConnection()
            self.protocol = None
            self.application = None

        s = self.protocol.getStream(0)
        d = s.sendStatus(code='NetConnection.Connection.Closed',
            description='Client disconnected.')

        d.addCallback(cb)

        return d

    def checkBandwidth(self):
        pass


class Application(object):
    """
    """

    implements(IApplication)

    client = Client

    def __init__(self):
        self.clients = {}
        self.streams = {}

    def startup(self):
        """
        Called when the application is starting up.
        """

    def shutdown(self):
        """
        Called when the application is closed.
        """

    def acceptConnection(self, client):
        """
        Called when this application has accepted the client connection.
        """
        clientId = util.generateBytes(9, readable=True)
        client.id = clientId

        self.clients[client] = clientId
        self.clients[clientId] = client

    def disconnect(self, client):
        """
        Removes the C{client} from this application.
        """
        try:
            del self.clients[client]
            del self.clients[client.id]
        except KeyError:
            pass

        client.id = None

    def buildClient(self, protocol):
        """
        Create an instance of a subclass of L{Client}. Override this method to
        alter how L{Client} instances are created.

        @param protocol: The L{rtmp.ServerProtocol} instance.
        """
        c = self.client()
        c.protocol = protocol

        return c

    def onConnect(self, client, **kwargs):
        """
        Called when a connection request is made to this application. Must
        return a C{bool} (or a L{defer.Deferred} returning a C{bool}) which
        determines the result of the connection request.

        If C{True} is returned then the connection is accepted. If C{False} is
        returned then the connection is rejected

        @param client: The client requesting the connection.
        @type client: An instance of L{client_class}.
        @param kwargs: The arguments supplied as part of the connection
            request.
        @type kwargs: C{dict}
        """
        return True

    def getStream(self, name):
        """
        """
        try:
            return self.streams[name]
        except KeyError:
            s = self.streams[name] = stream.SubscriberStream()
            s.application = self
            s.name = name

        return self.streams[name]

    def onPublish(self, client, stream):
        """
        Called when a client attempts to publish to a stream.
        """

    def onUnpublish(self, client, stream):
        """
        Called when a client unpublishes a stream.
        """

    def onDisconnect(self, client):
        """
        Called when a client disconnects.
        """
        self.disconnect(client)


class ServerProtocol(rtmp.RTMPProtocol):
    """
    A basic RTMP protocol that will act like a server.
    """

    def onConnect(self, args):
        """
        Called when a 'connect' packet is received from the client.
        """
        if self.application:
            # This protocol has already successfully completed a connection
            # request.

            # TODO, kill the connection
            return status.status(
                code='NetConnection.Connect.Closed',
                description='Already connected.'
            )

        try:
            appName = args['app']
        except KeyError:
            return status.status(
                code='NetConnection.Connect.Failed',
                description='Bad connect packet (missing `app` key)'
            )

        self.application = self.factory.getApplication(appName)

        if self.application is None:
            return status.error(
                code='NetConnection.Connect.InvalidApp',
                description='Unknown application \'%s\'' % (appName,)
            )

        self.client = self.application.buildClient(self)
        self.pendingConnection = defer.Deferred()

        def cb(res):
            if res is False:
                self.pendingConnection = None

                return status.error(
                    code='NetConnection.Connect.Rejected',
                    description='Authorization is required'
                )

            self.application.acceptConnection(self.client)

            s = self.getStream(0)

            s.writeEvent(event.DownstreamBandwidth(self.factory.downstreamBandwidth), channelId=2)
            s.writeEvent(event.UpstreamBandwidth(self.factory.upstreamBandwidth, 2), channelId=2)

            # clear the stream
            d = s.writeEvent(event.ControlEvent(0, 0), channelId=2)

            def sendStatus(res):
                x = {'fmsVer': self.factory.fmsVer, 'capabilities': 31}

                def y(res):
                    self.client.registerApplication(self.application)

                    return res

                self.pendingConnection.addCallback(y)

                self.pendingConnection.callback((x, status.status(
                    code=u'NetConnection.Connect.Success',
                    description=u'Connection succeeded.',
                    objectEncoding=0
                )))

                self.pendingConnection = None

            d.addCallback(sendStatus)

            # TODO: A timeout for the pendingConnection
            return self.pendingConnection

        def eb(f):
            print 'failed app.onConnect', f
            return status.status(
                code='NetConnection.Connect.Failed',
                description='Internal Server Error'
            )

        d = defer.maybeDeferred(self.application.onConnect, self.client, **args)

        d.addCallback(cb)

        if d.called:
            return d

        return self.pendingConnection

    def createStream(self):
        """
        """
        streamId = self.getNextAvailableStreamId()

        self.registerStream(streamId, stream.Stream(self))

        return streamId

    def onDownstreamBandwidth(self, bandwidth):
        self.client.upstreamBandwidth = bandwidth

        self.client.checkBandwidth()


class ServerFactory(protocol.ServerFactory):
    """
    RTMP server protocol factory.

    Maintains a collection of applications that RTMP clients connect and
    interact with.

    @ivar applications: A collection of active applications.
    @type applications: C{dict} of C{name} -> L{IApplication}
    @ivar _pendingApplications: A collection of applications that are pending
        activation.
    @type _pendingApplications: C{dict} of C{name} -> L{IApplication}
    """

    protocol = ServerProtocol
    protocolVersion = version.RTMP

    upstreamBandwidth = 2500000L
    downstreamBandwidth = 2500000L
    fmsVer = u'FMS/3,5,1,516'

    def __init__(self, applications=None):
        self.applications = {}
        self._pendingApplications = {}

        if applications:
            for name, app in applications.items():
                self.registerApplication(name, app)

    def getControlStream(self, protocol, streamId):
        """
        Creates and returns the stream for controlling server side protocol
        instances.

        @param protocol: The L{ServerProtocol} instance created by
            L{buildProtocol}
        @param streamId: The streamId for this control stream. Always 0.
        """
        return ServerControlStream(protocol, streamId)

    def getApplication(self, name):
        """
        Returns the active L{IApplication} instance related to C{name}. If
        there is no active application, C{None} is returned.
        """
        return self.applications.get(name, None)

    def registerApplication(self, name, app):
        """
        Registers the application to this factory instance. Returns a deferred
        which will signal the completion of the registration process.

        @param name: The name of the application. This is the name that the
            player will use when connecting to this server. An example::

            RTMP uri: http://appserver.mydomain.com/webApp; name: webApp.
        @param app: The L{IApplication} object that will interact with the
            RTMP clients.
        @return: A deferred signalling the completion of the registration
            process.
        """
        if name in self._pendingApplications or name in self.applications:
            raise InvalidApplication(
                '%r is already a registered application' % (name,))

        self._pendingApplications[name] = app

        d = defer.maybeDeferred(app.startup)

        def cleanup_pending(r):
            try:
                del self._pendingApplications[name]
            except KeyError:
                raise InvalidApplication('Pending application %r not found '
                    '(already unregistered?)' % (name,))

            return r

        def attach_application(res):
            self.applications[name] = app
            app.factory = self
            app.name = name

            return res

        d.addBoth(cleanup_pending).addCallback(attach_application)

        return d

    def unregisterApplication(self, name):
        """
        Unregisters and removes the named application from this factory. Any
        subsequent connect attempts to the C{name} will be met with an error.

        @return: A L{defer.Deferred} when the process is complete. The result
            will be the application instance that was successfully unregistered.
        """
        try:
            app = self._pendingApplications.pop(name)

            return defer.succeed(app)
        except KeyError:
            pass

        try:
            app = self.applications[name]
        except KeyError:
            raise InvalidApplication('Unknown application %r' % (name,))

        # TODO: run through the attached clients and signal the app shutdown.
        d = defer.maybeDeferred(app.shutdown)

        def cb(res):
            app = self.applications.pop(name)
            app.factory = None
            app.name = None

            return app

        d.addBoth(cb)

        return d

    def buildHandshakeNegotiator(self, protocol):
        """
        Returns a negotiator capable of handling server side handshakes.

        @param protocol: The L{ServerProtocol} requiring handshake negotiations.
        """
        i = handshake.get_implementation(self.protocolVersion)

        return i.ServerNegotiator(protocol, protocol.transport)
