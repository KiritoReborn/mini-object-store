import {
  Archive,
  Braces,
  File,
  FileAudio2,
  FileImage,
  FileText,
  FileVideo2,
} from "lucide-react";
import { fileKind } from "../format";

export function FileIcon({
  mime,
  large = false,
}: {
  mime: string;
  large?: boolean;
}) {
  const kind = fileKind(mime);
  const Icon =
    {
      Image: FileImage,
      Video: FileVideo2,
      Audio: FileAudio2,
      Archive,
      Code: Braces,
      Document: FileText,
      File,
    }[kind] ?? File;
  return (
    <span
      className={`file-icon ${kind.toLowerCase()} ${large ? "large" : ""}`}
      aria-hidden="true"
    >
      <Icon size={large ? 27 : 19} strokeWidth={1.6} />
    </span>
  );
}
