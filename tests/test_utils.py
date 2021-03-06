# Tests for the anymail/utils.py module
# (not to be confused with utilities for testing found in in tests/utils.py)
import base64

import six
from django.test import SimpleTestCase, RequestFactory, override_settings
from django.utils.translation import ugettext_lazy, string_concat

from anymail.exceptions import AnymailInvalidAddress
from anymail.utils import (ParsedEmail,
                           is_lazy, force_non_lazy, force_non_lazy_dict, force_non_lazy_list,
                           update_deep,
                           get_request_uri, get_request_basic_auth)


class ParsedEmailTests(SimpleTestCase):
    """Test utils.ParsedEmail"""

    # Anymail (and Djrill) have always used EmailMessage.encoding, which defaults to None.
    # (Django substitutes settings.DEFAULT_ENCODING='utf-8' when converting to a mime message,
    # but Anymail has never used that code.)
    ADDRESS_ENCODING = None

    def test_simple_email(self):
        parsed = ParsedEmail("test@example.com", self.ADDRESS_ENCODING)
        self.assertEqual(parsed.email, "test@example.com")
        self.assertEqual(parsed.name, "")
        self.assertEqual(parsed.address, "test@example.com")

    def test_display_name(self):
        parsed = ParsedEmail('"Display Name, Inc." <test@example.com>', self.ADDRESS_ENCODING)
        self.assertEqual(parsed.email, "test@example.com")
        self.assertEqual(parsed.name, "Display Name, Inc.")
        self.assertEqual(parsed.address, '"Display Name, Inc." <test@example.com>')

    def test_obsolete_display_name(self):
        # you can get away without the quotes if there are no commas or parens
        # (but it's not recommended)
        parsed = ParsedEmail('Display Name <test@example.com>', self.ADDRESS_ENCODING)
        self.assertEqual(parsed.email, "test@example.com")
        self.assertEqual(parsed.name, "Display Name")
        self.assertEqual(parsed.address, 'Display Name <test@example.com>')

    def test_unicode_display_name(self):
        parsed = ParsedEmail(u'"Unicode \N{HEAVY BLACK HEART}" <test@example.com>', self.ADDRESS_ENCODING)
        self.assertEqual(parsed.email, "test@example.com")
        self.assertEqual(parsed.name, u"Unicode \N{HEAVY BLACK HEART}")
        # display-name automatically shifts to quoted-printable/base64 for non-ascii chars:
        self.assertEqual(parsed.address, '=?utf-8?b?VW5pY29kZSDinaQ=?= <test@example.com>')

    def test_invalid_display_name(self):
        with self.assertRaises(AnymailInvalidAddress):
            # this parses as multiple email addresses, because of the comma:
            ParsedEmail('Display Name, Inc. <test@example.com>', self.ADDRESS_ENCODING)

    def test_none_address(self):
        # used for, e.g., telling Mandrill to use template default from_email
        parsed = ParsedEmail(None, self.ADDRESS_ENCODING)
        self.assertEqual(parsed.email, None)
        self.assertEqual(parsed.name, None)
        self.assertEqual(parsed.address, None)

    def test_empty_address(self):
        with self.assertRaises(AnymailInvalidAddress):
            ParsedEmail('', self.ADDRESS_ENCODING)

    def test_whitespace_only_address(self):
        with self.assertRaises(AnymailInvalidAddress):
            ParsedEmail(' ', self.ADDRESS_ENCODING)


class LazyCoercionTests(SimpleTestCase):
    """Test utils.is_lazy and force_non_lazy*"""

    def test_is_lazy(self):
        self.assertTrue(is_lazy(ugettext_lazy("lazy string is lazy")))
        self.assertTrue(is_lazy(string_concat(ugettext_lazy("concatenation"),
                                              ugettext_lazy("is lazy"))))

    def test_not_lazy(self):
        self.assertFalse(is_lazy(u"text not lazy"))
        self.assertFalse(is_lazy(b"bytes not lazy"))
        self.assertFalse(is_lazy(None))
        self.assertFalse(is_lazy({'dict': "not lazy"}))
        self.assertFalse(is_lazy(["list", "not lazy"]))
        self.assertFalse(is_lazy(object()))
        self.assertFalse(is_lazy([ugettext_lazy("doesn't recurse")]))

    def test_force_lazy(self):
        result = force_non_lazy(ugettext_lazy(u"text"))
        self.assertIsInstance(result, six.text_type)
        self.assertEqual(result, u"text")

    def test_force_concat(self):
        result = force_non_lazy(string_concat(ugettext_lazy(u"text"), ugettext_lazy("concat")))
        self.assertIsInstance(result, six.text_type)
        self.assertEqual(result, u"textconcat")

    def test_force_string(self):
        result = force_non_lazy(u"text")
        self.assertIsInstance(result, six.text_type)
        self.assertEqual(result, u"text")

    def test_force_bytes(self):
        result = force_non_lazy(b"bytes \xFE")
        self.assertIsInstance(result, six.binary_type)
        self.assertEqual(result, b"bytes \xFE")

    def test_force_none(self):
        result = force_non_lazy(None)
        self.assertIsNone(result)

    def test_force_dict(self):
        result = force_non_lazy_dict({'a': 1, 'b': ugettext_lazy(u"b"),
                                 'c': {'c1': ugettext_lazy(u"c1")}})
        self.assertEqual(result, {'a': 1, 'b': u"b", 'c': {'c1': u"c1"}})
        self.assertIsInstance(result['b'], six.text_type)
        self.assertIsInstance(result['c']['c1'], six.text_type)

    def test_force_list(self):
        result = force_non_lazy_list([0, ugettext_lazy(u"b"), u"c"])
        self.assertEqual(result, [0, u"b", u"c"])  # coerced to list
        self.assertIsInstance(result[1], six.text_type)


class UpdateDeepTests(SimpleTestCase):
    """Test utils.update_deep"""

    def test_updates_recursively(self):
        first = {'a': {'a1': 1, 'aa': {}}, 'b': "B"}
        second = {'a': {'a2': 2, 'aa': {'aa1': 11}}}
        result = update_deep(first, second)
        self.assertEqual(first, {'a': {'a1': 1, 'a2': 2, 'aa': {'aa1': 11}}, 'b': "B"})
        self.assertIsNone(result)  # modifies first in place; doesn't return it (same as dict.update())

    def test_overwrites_sequences(self):
        """Only mappings are handled recursively; sequences are considered atomic"""
        first = {'a': [1, 2]}
        second = {'a': [3]}
        update_deep(first, second)
        self.assertEqual(first, {'a': [3]})

    def test_handles_non_dict_mappings(self):
        """Mapping types in general are supported"""
        from collections import OrderedDict, defaultdict
        first = OrderedDict(a=OrderedDict(a1=1), c={'c1': 1})
        second = defaultdict(None, a=dict(a2=2))
        update_deep(first, second)
        self.assertEqual(first, {'a': {'a1': 1, 'a2': 2}, 'c': {'c1': 1}})


@override_settings(ALLOWED_HOSTS=[".example.com"])
class RequestUtilsTests(SimpleTestCase):
    """Test utils.get_request_* helpers"""

    def setUp(self):
        self.request_factory = RequestFactory()
        super(RequestUtilsTests, self).setUp()

    @staticmethod
    def basic_auth(username, password):
        """Return HTTP_AUTHORIZATION header value for basic auth with username, password"""
        credentials = base64.b64encode("{}:{}".format(username, password).encode('utf-8')).decode('utf-8')
        return "Basic {}".format(credentials)

    def test_get_request_basic_auth(self):
        # without auth:
        request = self.request_factory.post('/path/to/?query',
                                            HTTP_HOST='www.example.com',
                                            HTTP_SCHEME='https')
        self.assertIsNone(get_request_basic_auth(request))

        # with basic auth:
        request = self.request_factory.post('/path/to/?query',
                                            HTTP_HOST='www.example.com',
                                            HTTP_AUTHORIZATION=self.basic_auth('user', 'pass'))
        self.assertEqual(get_request_basic_auth(request), "user:pass")

        # with some other auth
        request = self.request_factory.post('/path/to/?query',
                                            HTTP_HOST='www.example.com',
                                            HTTP_AUTHORIZATION="Bearer abcde12345")
        self.assertIsNone(get_request_basic_auth(request))

    def test_get_request_uri(self):
        # without auth:
        request = self.request_factory.post('/path/to/?query', secure=True,
                                            HTTP_HOST='www.example.com')
        self.assertEqual(get_request_uri(request),
                         "https://www.example.com/path/to/?query")

        # with basic auth:
        request = self.request_factory.post('/path/to/?query', secure=True,
                                            HTTP_HOST='www.example.com',
                                            HTTP_AUTHORIZATION=self.basic_auth('user', 'pass'))
        self.assertEqual(get_request_uri(request),
                         "https://user:pass@www.example.com/path/to/?query")

    @override_settings(SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
                       USE_X_FORWARDED_HOST=True)
    def test_get_request_uri_with_proxy(self):
        request = self.request_factory.post('/path/to/?query', secure=False,
                                            HTTP_HOST='web1.internal',
                                            HTTP_X_FORWARDED_PROTO='https',
                                            HTTP_X_FORWARDED_HOST='secret.example.com:8989',
                                            HTTP_AUTHORIZATION=self.basic_auth('user', 'pass'))
        self.assertEqual(get_request_uri(request),
                         "https://user:pass@secret.example.com:8989/path/to/?query")
