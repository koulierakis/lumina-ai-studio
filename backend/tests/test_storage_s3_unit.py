import io

import storage


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[(Bucket, Key)] = (Body, ContentType)

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)][0])}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


def test_s3_storage_keeps_voice_samples_outside_ephemeral_disk(monkeypatch):
    client = FakeS3()
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "lumina-media")
    monkeypatch.setattr(storage, "_s3_client", lambda: client)

    filename, location, size = storage.save_bytes(b"voice-sample", "audio/wav", "reference")
    assert location == f"s3://lumina-media/references/{filename}"
    assert size == len(b"voice-sample")
    assert storage.read_bytes(filename, "reference") == b"voice-sample"

    storage.delete_file(filename, "reference")
    assert client.objects == {}
