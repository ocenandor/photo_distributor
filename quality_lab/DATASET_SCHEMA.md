# Quality Lab Dataset Schema

The lab stores private data under `quality_lab/data/`.

## Images

```text
quality_lab/data/images/<image_id>.jpg
```

`image_id` is usually the file stem.

## References

```text
quality_lab/data/references/<person_id>/<reference_file>.jpg
```

`person_id` should be stable and human-readable, for example:

```text
person_a
sofia
guest_001
```

Reference photos are deliberately separate from event photos. The lab run reads
all images in each `references/<person_id>/` folder, computes embeddings, and
uses those embeddings only for matching.

## Labels

`quality_lab/data/labels.json`:

```json
{
  "people": {
    "person_a": {
      "display_name": "Person A"
    }
  },
  "images": {
    "photo_001": {
      "path": "quality_lab/data/images/photo_001.jpg",
      "photo_subjects": ["person_a"],
      "notes": "",
      "faces": {
        "run_face_id": {
          "is_face": true,
          "person_id": "person_a",
          "is_subject": true,
          "quality": "good",
          "occlusion": "none",
          "pose": "frontal",
          "notes": ""
        }
      }
    }
  }
}
```

## Face Label Fields

- `is_face`: `true` if the detection is a real face, `false` for false positives.
- `person_id`: known person id, or `null` if unknown.
- `is_subject`: `true` if this person is an intended subject of the photo.
- `quality`: one of `good`, `ok`, `bad`.
- `occlusion`: one of `none`, `mask`, `glasses`, `sunglasses`, `hand`, `other`.
- `pose`: one of `frontal`, `three_quarter`, `profile`, `away`, `unknown`.
- `notes`: free-form comments.

## Metrics We Care About

Detection quality:

- false positive detections;
- missed intended subject faces;
- too-small/background detections.

Recognition quality:

- same-person similarity distribution;
- different-person similarity distribution;
- threshold precision/recall.

Photo relevance:

- whether a matched person should receive the photo;
- whether group photos include all intended subjects;
- whether background-only appearances are filtered out.
