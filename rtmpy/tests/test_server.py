# Copyright the RTMPy Project
#
# RTMPy is free software: you can redistribute it and/or modify it under the
# terms of the GNU Lesser General Public License as published by the Free
# Software Foundation, either version 2.1 of the License, or (at your option)
# any later version.
#
# RTMPy is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for more
# details.
#
# You should have received a copy of the GNU Lesser General Public License along
# with RTMPy.  If not, see <http://www.gnu.org/licenses/>.

"""
"""

from twisted.trial import unittest
from twisted.internet import defer, reactor, protocol
from twisted.test.proto_helpers import StringTransportWithDisconnection, StringIOWithoutClosing

from rtmpy import server, exc, rpc
from rtmpy.protocol.rtmp import message



class SimpleApplication(object):
    """
    An L{server.IApplication} that returns a deferred for all that it can.
    """

    factory = None
    name = None
    client = None

    ret = None
    reject = False

    def __init__(self):
        self.events = []

    def _add_event(self, name, args, kwargs):
        self.events.append((name, args, kwargs))

    def startup(self, *args, **kwargs):
        self._add_event('startup', args, kwargs)

        return self.ret

    def shutdown(self, *args, **kwargs):
        self._add_event('shutdown', args, kwargs)

        return self.ret

    def buildClient(self, *args, **kwargs):
        self._add_event('build-client', args, kwargs)

        return self.client

    def onConnect(self, *args, **kwargs):
        self._add_event('on-connect', args, kwargs)

        return not self.reject

    def onConnectAccept(self, *args, **kwargs):
        self._add_event('on-connect-accept', args, kwargs)

    def onConnectReject(self, *args, **kwargs):
        self._add_event('on-connect-reject', args, kwargs)

    def acceptConnection(self, *args, **kwargs):
        self._add_event('accept-connection', args, kwargs)

    def onAppStart(self, *args, **kwargs):
        self._add_event('on-app-start', args, kwargs)


class MockProtocol(object):
    """
    A mock protocol used to test protocol.transport.getPeer() requests
    """
    class Transport(object):

        def __init__(self, good=True):
            if good:
                self._peer = self.GoodPeer()
            else:
                self._peer = self.BadPeer()

        class GoodPeer(object):
            host = "127.0.0.1"

        class BadPeer(object):
            pass

        def getPeer(self):
            return self._peer

    def __init__(self, good=True):
        self.transport = self.Transport(good)





class ApplicationRegisteringTestCase(unittest.TestCase):
    """
    Tests for L{server.ServerFactory.registerApplication}
    """

    def setUp(self):
        self.factory = server.ServerFactory()
        self.app = SimpleApplication()

    def test_create(self):
        """
        Test initial args for L{server.ServerFactory}
        """
        self.factory = server.ServerFactory({'foo': self.app})

        self.assertEqual(self.factory.applications, {'foo': self.app})

        d = self.app.ret = defer.Deferred()

        self.factory = server.ServerFactory({'foo': self.app})

        self.assertEqual(self.factory.applications, {})

        def cb(res):
            self.assertEqual(self.factory.applications, {'foo': self.app})

        reactor.callLater(0, d.callback, None)

    def test_invalid_pending(self):
        """
        Pending applications cannot be registered twice.
        """
        self.factory._pendingApplications['foo'] = None

        self.assertRaises(exc.InvalidApplication,
            self.factory.registerApplication, 'foo', None)

    def test_invalid_active(self):
        """
        Active applications cannot be registered twice.
        """
        self.factory.applications['foo'] = None

        self.assertRaises(exc.InvalidApplication,
            self.factory.registerApplication, 'foo', None)

    def test_deferred_startup(self):
        """
        Registering an application can be paused whilst the app is startup is
        called.
        """
        d = self.app.ret = defer.Deferred()
        ret = self.factory.registerApplication('foo', self.app)

        self.assertIsInstance(ret, defer.Deferred)
        self.assertEqual(self.app.factory, None)
        self.assertEqual(self.app.name, None)
        self.assertTrue('foo' in self.factory._pendingApplications)
        self.assertFalse('foo' in self.factory.applications)

        def cb(res):
            self.assertEqual(res, None)

            self.assertIdentical(self.app.factory, self.factory)
            self.assertEqual(self.app.name, 'foo')
            self.assertFalse('foo' in self.factory._pendingApplications)
            self.assertTrue('foo' in self.factory.applications)

        ret.addCallback(cb)

        reactor.callLater(0, d.callback, None)

        return ret

    def test_failed_deferred(self):
        """
        An error in app.startup should stop the registering process
        """
        def blowup():
            raise RuntimeError

        self.patch(self.app, 'startup', blowup)

        ret = self.factory.registerApplication('foo', self.app)

        self.assertIsInstance(ret, defer.Deferred)

        def eb(fail):
            fail.trap(RuntimeError)

            self.assertEqual(self.app.factory, None)
            self.assertEqual(self.app.name, None)
            self.assertFalse('foo' in self.factory._pendingApplications)
            self.assertFalse('foo' in self.factory.applications)

        ret.addErrback(eb)

        return ret


class ApplicationUnregisteringTestCase(unittest.TestCase):
    """
    Tests for L{server.ServerFactory.unregisterApplication}
    """

    def setUp(self):
        self.factory = server.ServerFactory()
        self.app = SimpleApplication()

    def test_not_registered(self):
        """
        Unregistering an unknown app should error.
        """
        self.assertRaises(exc.InvalidApplication,
            self.factory.unregisterApplication, 'foo')

    def test_unregister_pending(self):
        """
        Unregistering a pending application should immediately succeed.
        """
        # this never gets its callback fired, meaning that after registering
        # the application, it is considered pending.
        self.app.ret = defer.Deferred()

        self.factory.registerApplication('foo', self.app)

        self.assertTrue('foo' in self.factory._pendingApplications)

        d = self.factory.unregisterApplication('foo')

        def cb(res):
            self.assertIdentical(res, self.app)

        d.addCallback(cb)

        return d

    def test_simple_unregister(self):
        """
        app.shutdown doesn't need to return a deferred
        """
        self.factory.registerApplication('foo', self.app)

        ret = self.factory.unregisterApplication('foo')

        self.assertIsInstance(ret, defer.Deferred)

        def cb(res):
            self.assertIdentical(res, self.app)

            self.assertEqual(self.app.factory, None)
            self.assertEqual(self.app.name, None)
            self.assertFalse('foo' in self.factory._pendingApplications)
            self.assertFalse('foo' in self.factory.applications)

        ret.addCallback(cb)

        return ret

    def test_deferred(self):
        """
        app.shutdown can return a deferred
        """
        self.factory.registerApplication('foo', self.app)
        d = self.app.ret = defer.Deferred()

        ret = self.factory.unregisterApplication('foo')

        self.assertIsInstance(ret, defer.Deferred)

        def cb(res):
            self.assertIdentical(res, self.app)

            self.assertEqual(self.app.factory, None)
            self.assertEqual(self.app.name, None)
            self.assertFalse('foo' in self.factory._pendingApplications)
            self.assertFalse('foo' in self.factory.applications)

        ret.addCallback(cb)

        reactor.callLater(0, d.callback, None)

        return ret

    def test_deferred_failure(self):
        """
        Removing the app from the factory should not fail due to app.shutdown
        erroring.
        """
        self.factory.registerApplication('foo', self.app)

        d = self.app.ret = defer.Deferred()

        def boom(res):
            self.executed = True

            raise RuntimeError

        d.addCallback(boom)

        ret = self.factory.unregisterApplication('foo')

        self.assertIsInstance(ret, defer.Deferred)

        def cb(res):
            self.assertIdentical(res, self.app)
            self.assertTrue(self.executed)

            self.assertEqual(self.app.factory, None)
            self.assertEqual(self.app.name, None)
            self.assertFalse('foo' in self.factory._pendingApplications)
            self.assertFalse('foo' in self.factory.applications)

        ret.addCallback(cb)

        reactor.callLater(0, d.callback, None)

        return ret


class ServerFactoryTestCase(unittest.TestCase):
    """
    """

    def setUp(self):
        self.factory = server.ServerFactory()
        self.protocol = self.factory.buildProtocol(None)
        self.transport = StringTransportWithDisconnection()
        self.protocol.transport = self.transport
        self.transport.protocol = self.protocol

        self.protocol.connectionMade()
        self.protocol.handshakeSuccess('')


    def connect(self, app, protocol):
        client = app.buildClient(self.protocol, {'app': 'foo'})

        app.acceptConnection(client)

        protocol.connected = True
        protocol.client = client
        protocol.application = app

        return client

    def createStream(self, protocol):
        """
        Returns the L{server.NetStream} as created by the protocol
        """
        return protocol.getStream(protocol.createStream())



class ConnectingTestCase(unittest.TestCase):
    """
    Tests all facets of connecting to an RTMP server.
    """

    def setUp(self):
        self.file = StringIOWithoutClosing()
        self.transport = protocol.FileWrapper(self.file)

        self.factory = server.ServerFactory()
        self.protocol = self.factory.buildProtocol(None)

        self.protocol.factory = self.factory

        self.protocol.transport = self.transport
        self.protocol.connectionMade()
        self.protocol.handshakeSuccess('')

        self.messages = []

        def send_message(*args):
            self.messages.append(args)

        self.patch(self.protocol, 'sendMessage', send_message)

        self.control = self.protocol.getStream(0)


    def assertStatus(self, code=None, description=None, level='status'):
        """
        Ensures that a status message has been sent.
        """
        stream, msg = self.messages.pop(0)

        self.assertEqual(self.messages, [])

        self.assertIdentical(stream, self.control)

        self.assertIsInstance(msg, message.Invoke)
        self.assertEqual(msg.name, 'onStatus')

        _, args = msg.argv

        self.assertEqual(_, None)

        if code is not None:
            self.assertEqual(args['code'], code)

        if description is not None:
            self.assertEqual(args['description'], description)

        self.assertEqual(args['level'], level)


    def assertErrorStatus(self, code=None, description=None):
        """
        Ensures that a status message has been sent.
        """
        if code is None:
            code = 'NetConnection.Connect.Failed'

        if description is None:
            description = 'Internal Server Error'

        self.assertStatus(code, description, 'error')


    def assertMessage(self, msg, type_, **state):
        """
        Ensure that the msg is of a particular type and state
        """
        self.assertEqual(message.typeByClass(msg), type_)

        d = msg.__dict__

        for k, v in state.copy().iteritems():
            self.assertEqual(v, d[k])
            del state[k]

        self.assertEqual(state, {})

    def connect(self, params, *args):
        return self.control.onConnect(params, *args)

    def test_invoke(self):
        """
        Make sure that invoking connect call self.protocol.onConnect
        """
        my_args = {'foo': 'bar'}
        self.executed = False

        def connect(args):
            self.executed = True
            self.assertEqual(args, my_args)

        self.patch(self.protocol, 'onConnect', connect)

        d = self.control.onInvoke('connect', 0, [my_args], 0)

        return d

    def test_missing_app_key(self):
        """
        RTMP connect packets contain {'app': 'name_of_app'}.
        """
        d = self.connect({})

        def cb(res):
            self.assertEqual(res, {
                'code': 'NetConnection.Connect.Failed',
                'description': "Bad connect packet (missing 'app' key)",
                'level': 'error',
                'objectEncoding': 0
            })

        d.addCallback(cb)

        return d

    def test_random_failure(self):
        """
        If something random goes wrong, make sure the status is correctly set.
        """
        def bork(*args):
            raise EnvironmentError('woot')

        self.patch(self.protocol, '_onConnect', bork)

        d = self.connect({})

        def cb(res):
            self.assertEqual(res, {
                'code': 'NetConnection.Connect.Failed',
                'description': 'woot',
                'level': 'error',
                'objectEncoding': 0
            })


        d.addCallback(cb)

        return d

    def test_unknown_application(self):
        self.assertEqual(self.factory.getApplication('what'), None)

        d = self.connect({'app': 'what'})

        def cb(res):
            self.assertEqual(res, {
                'code': 'NetConnection.Connect.InvalidApp',
                'description': "Unknown application 'what'",
                'level': 'error',
                'objectEncoding': 0
            })

        d.addCallback(cb)

        return d

    def test_success(self):
        """
        Ensure a successful connection to application
        """
        self.factory.applications['what'] = SimpleApplication()

        d = self.connect({'app': 'what'})

        def check_status(res):
            self.assertIsInstance(res, rpc.CommandResult)
            self.assertEqual(res.command, {
                'capabilities': 31, 'fmsVer': 'FMS/3,5,1,516', 'mode': 1})
            self.assertEqual(res.result, {
                'code': 'NetConnection.Connect.Success',
                'objectEncoding': 0,
                'description': 'Connection succeeded.',
                'level': 'status'
            })

            msg, = self.messages.pop(0)

            self.assertMessage(msg, message.DOWNSTREAM_BANDWIDTH,
                bandwidth=2500000L)

            msg, = self.messages.pop(0)

            self.assertMessage(msg, message.UPSTREAM_BANDWIDTH,
                bandwidth=2500000L, extra=2)

            msg, = self.messages.pop(0)

            self.assertMessage(msg, message.CONTROL,
                type=0, value1=0)

            self.assertEqual(self.messages, [])

        d.addCallback(check_status)

        self.protocol.onDownstreamBandwidth(2000, 2)

        return d

    def test_connect_args(self):
        """
        Ensure a successful connection to application with optional user
        arguments being passed.

        The arguments should be available to various application methods
        such as onConnect, buildClient, etc.
        """
        a = self.factory.applications['what'] = SimpleApplication()
        a.client = object()

        client_params = {'app': 'what'} # Connect packet parameters
        client_args = ("foo", "bar") # Arguments passed to NC.connect()

        d = self.connect(client_params, *client_args)

        def check_status(res):
            name, args, kwargs = a.events.pop()
            self.assertEqual(name, 'on-connect-accept')

            name, args, kwargs = a.events.pop()
            self.assertEqual(name, 'accept-connection')

            name, args, kwargs = a.events.pop()
            self.assertEqual(name, 'on-connect')
            self.assertIdentical(args[0], a.client)
            self.assertEqual(args[1:], client_args)
            self.assertEqual(len(args), 3)
            self.assertEqual(kwargs, {})

            name, args, kwargs = a.events.pop()
            self.assertEqual(name, 'build-client')
            self.assertIdentical(args[0], self.protocol)
            self.assertEqual(args[1], client_params)
            self.assertEqual(args[2:], client_args)
            self.assertEqual(len(args), 4)

        d.addCallback(check_status)

        self.protocol.onDownstreamBandwidth(2000, 2)

        return d

    def test_reject(self):
        """
        Test the connection being rejected
        """
        a = self.factory.applications['what'] = SimpleApplication()
        a.reject = True
        a.client = object()

        d = self.connect({'app': 'what'})

        def check_status(res):
            self.assertEqual(res, {
                'code': 'NetConnection.Connect.Rejected',
                'level': 'error',
                'description': 'Authorization is required',
                'objectEncoding': 0
            })

            self.assertEqual(self.messages, [])

            name, args, kwargs = a.events.pop()

            self.assertEqual(name, 'on-connect-reject')
            self.assertIdentical(args[0], a.client)
            self.assertEqual(len(args), 2)
            self.assertEqual(kwargs, {})

        d.addCallback(check_status)

        return d

    def test_reject_with_args(self):
        """
        Test that the arguments passed to NetConnection.connect() are passed
        to onConnectReject
        """
        a = self.factory.applications['what'] = SimpleApplication()
        a.reject = True
        a.client = object()

        client_params = {'app': 'what'} # Connect packet parameters
        client_args = ("foo", "bar") # Arguments passed to NC.connect()

        d = self.connect(client_params, *client_args)

        def check_status(res):
            name, args, kwargs = a.events.pop()

            self.assertEqual(name, 'on-connect-reject')
            self.assertIdentical(args[0], a.client)
            self.assertEqual(args[2:], client_args)
            self.assertEqual(len(args), 4)
            self.assertEqual(kwargs, {})

        d.addCallback(check_status)

        return d

    def test_client_properties(self):
        """
        Ensure that buildClient properly populates Client properties
        """
        a = server.Application()
        p = MockProtocol(True)

        client_params = {
            'flashVer': 'MAC 10,2,154,13', 'app': 'what',
            'pageUrl': 'http://foo.com/page',
            'tcUrl': 'rtmp://localhost/live'
            }

        c = a.buildClient(p, client_params)

        self.assertIdentical(c.nc, p)
        self.assertIdentical(c.application, a)
        self.assertEquals(c.ip, '127.0.0.1')
        self.assertEquals(c.agent, 'MAC 10,2,154,13')
        self.assertEquals(c.pageUrl, 'http://foo.com/page')
        self.assertEquals(c.uri, 'rtmp://localhost/live')
        self.assertEquals(c.protocol, 'rtmp')

        return

    def test_missing_client_properties(self):
        """
        Ensure that buildClient properly handles missing properties
        """
        a = server.Application()
        p = MockProtocol(False)

        client_params = {'app': 'what'}

        c = a.buildClient(p, client_params)

        self.assertIdentical(c.nc, p)
        self.assertIdentical(c.application, a)
        self.assertEquals(c.ip, None)
        self.assertEquals(c.agent, None)
        self.assertEquals(c.pageUrl, None)
        self.assertEquals(c.uri, None)
        self.assertEquals(c.protocol, None)

        return


class TestRuntimeError(RuntimeError):
    pass


class ApplicationInterfaceTestCase(ServerFactoryTestCase):
    """
    Tests for L{server.ServerProtocol} implementing the L{server.IApplication}
    interface correctly.
    """

    def setUp(self):
        ServerFactoryTestCase.setUp(self)

        self.app = server.Application()
        self.client = self.app.buildClient(self.protocol, {'app': 'foo'})
        self.app.acceptConnection(self.client)

        return self.factory.registerApplication('foo', self.app)

    def test_onDisconnect(self):
        """
        Ensure that C{onDisconnect} is called when calling C{app.disconnect}
        """
        self.executed = False

        def foo(client):
            self.assertIdentical(self.client, client)
            self.executed = True

        self.app.onDisconnect = foo

        self.app.disconnect(self.client)

        self.assertTrue(self.executed)

    def test_onDisconnect_error(self):
        """
        Ensure that if onDisconnect raises an error, that execution continues
        smoothly.
        """
        self.executed = False

        def foo(client):
            self.executed = True

            raise TestRuntimeError('Die!!')

        self.app.onDisconnect = foo

        self.app.disconnect(self.client)

        self.assertTrue(self.executed)
        self.flushLoggedErrors(TestRuntimeError)


class PublishingTestCase(ServerFactoryTestCase):
    """
    Tests for all facets of publishing a stream
    """

    def setUp(self):
        ServerFactoryTestCase.setUp(self)

        self.stream_status = {}

        self.app = server.Application()

        return self.factory.registerApplication('foo', self.app)


    def createStream(self):
        """
        Returns the L{server.NetStream} as created by the protocol
        """
        stream = self.protocol.getStream(self.protocol.createStream())

        def capture_status(s):
            self.stream_status[stream] = s

        stream.sendStatus = capture_status

        return stream


    def assertStatus(self, stream, s):
        self.assertEqual(self.stream_status[stream], s)


    def test_publish(self):
        """
        Test app, client and protocol state on a successful first time publish
        """
        self.client = self.connect(self.app, self.protocol)

        s = self.createStream()

        d = s.publish('foo')

        def cb(result):
            # app
            self.assertIdentical(result, self.app.streams['foo'])

            # stream
            self.assertIdentical(s.publisher, result)
            self.assertEqual(s.state, 'publishing')

            # result
            self.assertIdentical(result.stream, s)
            self.assertIdentical(result.client, self.client)
            self.assertEqual(result.subscribers, {})
            self.assertEqual(result.timestamp, 0)

            # rtmp status
            self.assertStatus(s, {
                'code': 'NetStream.Publish.Start',
                'description': 'foo is now published.',
                'clientid': self.client.id,
                'level': 'status'
            })


        return d.addCallback(cb)


    def test_not_connected(self):
        """
        Test when
        """
        s = self.createStream()

        self.assertFalse(self.protocol.connected)

        d = s.publish('foo')

        def eb(f):
            f.trap(exc.ConnectError)

            self.assertEqual(f.getErrorMessage(), 'Cannot publish stream - not connected')

            self.assertStatus(s, {
                'code': 'NetConnection.Call.Failed',
                'description': 'Cannot publish stream - not connected',
                'level': 'error'
            })

        return d.addErrback(eb)


    def test_kill_connection_after_successful_publish(self):
        """
        After a successful publish, the peer disconnects rudely. Check app state
        """
        self.client = self.connect(self.app, self.protocol)
        s = self.createStream()

        d = s.publish('foo')

        def kill_connection(result):
            self.transport.loseConnection()

            self.assertEqual(self.app.streams, {})
            self.assertEqual(self.app.clients, {})

            self.assertStatus(s, {
                'code': 'NetStream.Unpublish.Success',
                'description': u'foo is now unpublished.',
                'clientid': self.client.id,
                'level': 'status'
            })

        d.addCallback(kill_connection)

        return d


class PlayTestCase(ServerFactoryTestCase):
    """
    Tests for L{NetStream.play}
    """


    def setUp(self):
        ServerFactoryTestCase.setUp(self)

        self.app = server.Application()

        return self.factory.registerApplication('foo', self.app)


    def test_pending(self):
        """
        Test if the stream does not exist, the play command is put in a
        suspended state, until a stream with the right name is published.
        """
        client = self.connect(self.app, self.protocol)

        s = self.createStream(self.protocol)

        self.assertFalse('foo' in self.app.streams)

        d = s.play('foo')

        self.assertFalse(d.called)

        res = self.app.publishStream(client, s, 'foo')

        self.assertTrue('foo' in self.app.streams)
        self.assertTrue(s in res.subscribers)


    def test_existing(self):
        """
        Test if the stream does already exist, the play command is immediately
        completed.
        """
        client = self.connect(self.app, self.protocol)

        s = self.createStream(self.protocol)

        self.assertFalse('foo' in self.app.streams)

        self.app.publishStream(client, s, 'foo')

        d = s.play('foo')

        self.assertTrue(d.called)

        def cb(res):
            self.assertTrue(s in res.subscribers)

        d.addCallback(cb)

        return d
