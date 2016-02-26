# Copyright ClusterHQ Inc.  See LICENSE file for details.

"""
Effectful interface to boto.
"""

import os
from characteristic import attributes, Attribute
from effect import Effect, sync_performer, TypeDispatcher
from effect.do import do, do_return

import boto
from pyrsistent import PClass, pmap_field, PMap, field, discard, freeze
from twisted.python.filepath import FilePath


@attributes([
    "bucket",
    "routing_rules",
])
class UpdateS3RoutingRules(object):
    """
    Update the routing rules for an S3 bucket website endpoint.

    :ivar bytes bucket: Name of bucket to change routing rule for.
    :ivar boto.s3.website.RoutingRules routing_rules: New routing rules.
    """


@sync_performer
def perform_update_s3_routing_rules(dispatcher, intent):
    """
    See :class:`UpdateS3RoutingRule`.
    """
    s3 = boto.connect_s3()
    bucket = s3.get_bucket(intent.bucket)
    config = bucket.get_website_configuration_obj()
    config.routing_rules = intent.routing_rules
    bucket.set_website_configuration(config)


@attributes([
    "bucket",
    "target_prefix",
])
class UpdateS3ErrorPage(object):
    """
    Update the error_key for an S3 bucket website endpoint to point to a new
    path.

    If the key is changed, return the old key.

    :ivar bytes bucket: Name of bucket to change routing rule for.
    :ivar bytes target_prefix: Target prefix to redirect to.
    """
    @property
    def error_key(self):
        """
        """
        return u'{}error_pages/404.html'.format(self.target_prefix)


@sync_performer
def perform_update_s3_error_page(dispatcher, intent):
    """
    See :class:`UpdateS3ErrorPage`.
    """
    s3 = boto.connect_s3()
    bucket = s3.get_bucket(intent.bucket)
    config = bucket.get_website_configuration_obj()
    new_error_key = intent.error_key
    old_error_key = config.error_key
    if old_error_key == new_error_key:
        return None
    else:
        config.error_key = new_error_key
        bucket.set_website_configuration(config)
        return old_error_key


@attributes([
    "cname",
    "paths",
])
class CreateCloudFrontInvalidation(object):
    """
    Create a CloudFront invalidation request.

    :ivar bytes cname: A CNAME associated to the distribution to create an
        invalidation for.
    :ivar list paths: List of paths to invalidate.
    """


@sync_performer
def perform_create_cloudfront_invalidation(dispatcher, intent):
    """
    See :class:`CreateCloudFrontInvalidation`.
    """
    cf = boto.connect_cloudfront()
    distribution = [dist for dist in cf.get_all_distributions()
                    if intent.cname in dist.cnames][0]
    cf.create_invalidation_request(distribution.id, intent.paths)


@attributes([
    "bucket",
    Attribute("prefix", default_value=""),
    "keys",
])
class DeleteS3Keys(object):
    """
    Delete a list of keys from an S3 bucket.
    :ivar bytes bucket: Name of bucket to delete keys from.
    :ivar bytes prefix: Prefix to add to each key to delete.
    :ivar list keys: List of keys to be deleted.
    """


@sync_performer
def perform_delete_s3_keys(dispatcher, intent):
    """
    See :class:`DeleteS3Keys`.
    """
    s3 = boto.connect_s3()
    bucket = s3.get_bucket(intent.bucket)
    bucket.delete_keys(
        [intent.prefix + key
         for key in intent.keys])


@attributes([
    "source_bucket",
    Attribute("source_prefix", default_value=""),
    "destination_bucket",
    Attribute("destination_prefix", default_value=""),
    "keys",
])
class CopyS3Keys(object):
    """
    Copy a list of keys from one S3 bucket to another.

    :ivar bytes source_bucket: Name of bucket to copy keys from.
    :ivar bytes source_prefix: Prefix to add to each key to in
        ``source_bucket``.
    :ivar bytes destination_bucket: Name of bucket to copy keys to.
    :ivar bytes destination_prefix: Prefix to add to each key to in
        ``destination_bucket``.
    :ivar list keys: List of keys to be copied.
    """


EXTENSION_MIME_TYPES = {
    '.eot': 'application/vnd.ms-fontobject',
    '.gif': 'image/gif',
    '.html': 'text/html',
    '.jpg': 'image/jpeg',
    '.js': 'application/javascript',
    '.css': 'text/css',
    '.png': 'image/png',
    '.sh': 'text/plain',
    '.svg': 'image/svg+xml',
    '.ttf': 'application/x-font-ttf',
    '.txt': 'text/plain',
    '.woff': 'application/font-woff',
    '.yml': 'text/plain',
}


@sync_performer
def perform_copy_s3_keys(dispatcher, intent):
    """
    See :class:`CopyS3Keys`.
    """
    s3 = boto.connect_s3()
    source_bucket = s3.get_bucket(intent.source_bucket)
    for key in intent.keys:
        source_key = source_bucket.get_key(intent.source_prefix + key)

        # We are explicit about Content-Type here, since the upload tool
        # isn't smart enough to set the right Content-Type.
        destination_metadata = source_key.metadata
        for extention, content_type in EXTENSION_MIME_TYPES.items():
            if key.endswith(extention):
                destination_metadata['Content-Type'] = content_type
                break

        source_key.copy(
            dst_bucket=intent.destination_bucket,
            dst_key=intent.destination_prefix + key,
            metadata=destination_metadata,
        )


@attributes([
    "bucket",
    "prefix",
])
class ListS3Keys(object):
    """
    List the S3 keys in a bucket.

    Note that this returns a list with the prefixes stripped.

    :ivar bytes bucket: Name of bucket to list keys from.
    :ivar bytes prefix: Prefix of keys to be listed.
    """


@sync_performer
def perform_list_s3_keys(dispatcher, intent):
    """
    See :class:`ListS3Keys`.
    """
    s3 = boto.connect_s3()
    bucket = s3.get_bucket(intent.bucket)
    return {key.name[len(intent.prefix):]
            for key in bucket.list(intent.prefix)}


@attributes([
    "source_bucket",
    "source_prefix",
    "target_path",
    "filter_extensions",
])
class DownloadS3KeyRecursively(object):
    """
    Download the S3 files from a key in a bucket to a given directory.

    :ivar bytes source_bucket: Name of bucket to download keys from.
    :ivar bytes source_prefix: Download only files with this prefix.
    :ivar FilePath target_path: Directory to download files to.
    :ivar tuple filter_extensions: Download only files with extensions in this
        tuple.
    """


@sync_performer
@do
def perform_download_s3_key_recursively(dispatcher, intent):
    """
    See :class:`DownloadS3KeyRecursively`.
    """
    keys = yield Effect(
        ListS3Keys(prefix=intent.source_prefix + '/',
                   bucket=intent.source_bucket))
    for key in keys:
        if not key.endswith(intent.filter_extensions):
            continue
        path = intent.target_path.preauthChild(key)

        if not path.parent().exists():
            path.parent().makedirs()
        source_key = os.path.join(intent.source_prefix, key)
        yield Effect(
            DownloadS3Key(source_bucket=intent.source_bucket,
                          source_key=source_key,
                          target_path=path))


@attributes([
    "source_bucket",
    "source_key",
    "target_path",
])
class DownloadS3Key(object):
    """
    Download a file from S3.

    :ivar bytes source_bucket: Name of bucket to download key from.
    :ivar bytes source_key: Name of key to download.
    :ivar FilePath target_path: Path to download file to.
    """


@sync_performer
def perform_download_s3_key(dispatcher, intent):
    """
    See :class:`DownloadS3Key`.
    """
    s3 = boto.connect_s3()

    bucket = s3.get_bucket(intent.source_bucket)
    key = bucket.get_key(intent.source_key)
    if key is None:
        raise KeyError(intent.source_key)
    with intent.target_path.open('w') as target_file:
        key.get_contents_to_file(target_file)


@attributes([
    "source_bucket",
    "source_key",
])
class ReadS3Key(object):
    """
    Read a file from S3.

    :ivar bytes source_bucket: Name of bucket to read key from.
    :ivar bytes source_key: Name of key to read.
    """


@sync_performer
@do
def perform_read_s3_key(dispatcher, intent):
    """
    See :class:`ReadS3Key`.
    """
    target_file = FilePath(
        u'/tmp/{}.perform_read_s3_key'.format(
            __file__.replace(u"/", "!"),
        )
    ).temporarySibling()
    target_file.requireCreate(False)
    try:
        yield Effect(
            DownloadS3Key(
                source_bucket=intent.source_bucket,
                source_key=intent.source_key,
                target_path=target_file,
            )
        )
        yield do_return(target_file.getContent())
    finally:
        if target_file.exists():
            target_file.remove()


@attributes([
    "source_path",
    "target_bucket",
    "target_key",
    "files",
])
class UploadToS3Recursively(object):
    """
    Upload contents of a directory to S3, for given files.

    Note that this returns a list with the prefixes stripped.

    :ivar FilePath source_path: Prefix of files to be uploaded.
    :ivar bytes target_bucket: Name of the bucket to upload file to.
    :ivar bytes target_key: Name of the S3 key to upload file to.
    :ivar set files: Set of bytes, relative paths to files to upload.
    """


@sync_performer
@do
def perform_upload_s3_key_recursively(dispatcher, intent):
    """
    See :class:`UploadToS3Recursively`.
    """
    for child in intent.files:
        path = intent.source_path.preauthChild(child)
        if path.isfile():
            yield Effect(
                UploadToS3(
                    source_path=intent.source_path,
                    target_bucket=intent.target_bucket,
                    target_key="%s/%s" % (intent.target_key, child),
                    file=path,
                    ))


@attributes([
    "source_path",
    "target_bucket",
    "target_key",
    "file",
    Attribute("content_type", default_value=None),
])
class UploadToS3(object):
    """
    Upload a file to S3.

    :ivar FilePath source_path: See :class:`UploadToS3Recursively`.
    :ivar bytes target_bucket: See :class:`UploadToS3 Recursively`.
    :ivar bytes target_key: See :class:`UploadToS3Recursively`.
    :ivar FilePath file: Path to file to upload.
    :ivar bytes content_type: Optional content-type for file contents.
    """


@sync_performer
def perform_upload_s3_key(dispatcher, intent):
    """
    See :class:`UploadToS3`.
    """
    s3 = boto.connect_s3()
    bucket = s3.get_bucket(intent.target_bucket)
    headers = {}
    if intent.content_type is not None:
        headers['Content-Type'] = intent.content_type
    with intent.file.open() as source_file:
        key = bucket.new_key(intent.target_key)
        key.set_contents_from_file(source_file, headers=headers)
        key.make_public()

boto_dispatcher = TypeDispatcher({
    UpdateS3RoutingRules: perform_update_s3_routing_rules,
    UpdateS3ErrorPage: perform_update_s3_error_page,
    ListS3Keys: perform_list_s3_keys,
    DeleteS3Keys: perform_delete_s3_keys,
    CopyS3Keys: perform_copy_s3_keys,
    DownloadS3KeyRecursively: perform_download_s3_key_recursively,
    DownloadS3Key: perform_download_s3_key,
    ReadS3Key: perform_read_s3_key,
    UploadToS3Recursively: perform_upload_s3_key_recursively,
    UploadToS3: perform_upload_s3_key,
    CreateCloudFrontInvalidation: perform_create_cloudfront_invalidation,
})


class ContentTypeUnicode(unicode):
    """
    A Unicode string with an additional content-type field.
    """
    def __new__(cls, value, content_type):
        self = super(ContentTypeUnicode, cls).__new__(cls, unicode(value))
        self.content_type = content_type
        return self


class FakeAWSState(PClass):
    """
    The immutable state of ``FakeAWS``

    :ivar routing_rules: Dictionary of routing rules for S3 buckets. They are
        represented as dictonaries mapping key prefixes to replacements. Other
        types of rules and attributes are supported or represented.
    :ivar s3_buckets: Dictionary of fake S3 buckets. Each bucket is represented
        as a dictonary mapping keys to contents. Other attributes are ignored.
    :ivar cloudfront_invalidations: List of
        :class:`CreateCloudFrontInvalidation` that have been requested.
    """
    routing_rules = pmap_field(
        key_type=unicode,
        value_type=boto.s3.website.RoutingRules
    )
    s3_buckets = pmap_field(
        key_type=unicode,
        value_type=PMap
    )
    error_key = pmap_field(key_type=unicode, value_type=unicode)
    cloudfront_invalidations = field(initial=freeze([]))


@attributes(['state'])
class FakeAWS(object):
    """
    Enough of a fake implementation of AWS to test
    :func:`admin.release.publish_docs`.

    :ivar routing_rules: Dictionary of routing rules for S3 buckets. They are
        represented as dictonaries mapping key prefixes to replacements. Other
        types of rules and attributes are supported or represented.
    :ivar s3_buckets: Dictionary of fake S3 buckets. Each bucket is represented
        as a dictonary mapping keys to contents. Other attributes are ignored.
    :ivar cloudfront_invalidations: List of
        :class:`CreateCloudFrontInvalidation` that have been requested.
    """
    def __init__(self):
        self.initial_state = self.state

    @sync_performer
    def _perform_update_s3_routing_rules(self, dispatcher, intent):
        """
        See :class:`UpdateS3RoutingRule`.
        """
        self.state = self.state.transform(
            ['routing_rules', intent.bucket],
            intent.routing_rules
        )

    @sync_performer
    def _perform_update_s3_error_page(self, dispatcher, intent):
        """
        See :class:`UpdateS3ErrorPage`.
        """
        new_error_key = intent.error_key
        old_error_key = self.state.error_key.get(intent.bucket)
        self.state = self.state.transform(
            [u'error_key', intent.bucket],
            new_error_key
        )
        if old_error_key == new_error_key:
            return None
        return old_error_key

    @sync_performer
    def _perform_create_cloudfront_invalidation(self, dispatcher, intent):
        """
        See :class:`CreateCloudFrontInvalidation`.
        """
        self.state = self.state.transform(
            ['cloudfront_invalidations'],
            lambda l: l.append(intent)
        )

    @sync_performer
    def _perform_delete_s3_keys(self, dispatcher, intent):
        """
        See :class:`DeleteS3Keys`.
        """
        for key in intent.keys:
            self.state = self.state.transform(
                ['s3_buckets', intent.bucket, intent.prefix + key],
                discard,
            )

    @sync_performer
    def _perform_copy_s3_keys(self, dispatcher, intent):
        """
        See :class:`CopyS3Keys`.
        """
        source_bucket = self.state.s3_buckets[intent.source_bucket]
        for key in intent.keys:
            self.state = self.state.transform(
                ['s3_buckets',
                 intent.destination_bucket,
                 intent.destination_prefix + key],
                source_bucket[intent.source_prefix + key]
            )

    @sync_performer
    def _perform_list_s3_keys(self, dispatcher, intent):
        """
        See :class:`ListS3Keys`.
        """
        bucket = self.state.s3_buckets[intent.bucket]
        return {key[len(intent.prefix):]
                for key in bucket
                if key.startswith(intent.prefix)}

    @sync_performer
    def _perform_download_s3_key(self, dispatcher, intent):
        """
        See :class:`DownloadS3Key`.
        """
        bucket = self.state.s3_buckets[intent.source_bucket]
        intent.target_path.setContent(bucket[intent.source_key])

    @sync_performer
    def _perform_upload_s3_key(self, dispatcher, intent):
        """
        See :class:`UploadToS3`.
        """

        with intent.file.open() as source_file:
            content = source_file.read()
        # XXX: Need to think about this.
        # The fake currently only allows unicode content.
        content_type = intent.content_type
        if content_type is not None:
            content = ContentTypeUnicode(content, content_type)
        self.state = self.state.transform(
            ['s3_buckets', intent.target_bucket, intent.target_key],
            content
        )

    def get_dispatcher(self):
        """
        Get an :module:`effect` dispatcher for interacting with this
        :class:`FakeAWS`.
        """
        return TypeDispatcher({
            # Share implementation with real implementation
            DownloadS3KeyRecursively: perform_download_s3_key_recursively,
            UploadToS3Recursively: perform_upload_s3_key_recursively,
            ReadS3Key: perform_read_s3_key,

            # Fake implementation
            UpdateS3RoutingRules: self._perform_update_s3_routing_rules,
            UpdateS3ErrorPage: self._perform_update_s3_error_page,
            ListS3Keys: self._perform_list_s3_keys,
            DeleteS3Keys: self._perform_delete_s3_keys,
            CopyS3Keys: self._perform_copy_s3_keys,
            DownloadS3Key: self._perform_download_s3_key,
            UploadToS3: self._perform_upload_s3_key,
            CreateCloudFrontInvalidation:
                self._perform_create_cloudfront_invalidation,
        })


def fake_aws(routing_rules, s3_buckets):
    initial_state = FakeAWSState(
        routing_rules=routing_rules,
        s3_buckets=freeze(s3_buckets),
    )
    return FakeAWS(state=initial_state)
