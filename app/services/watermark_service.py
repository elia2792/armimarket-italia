import logging
import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("app.services.watermark_service")


class WatermarkService:
    @staticmethod
    def apply_watermark(image_bytes: bytes, text: str = "ArmiMarket Italia - Annuncio Conforme T.U.L.P.S.") -> bytes:
        """
        Applica una filigrana semitrasparente discreta ma indelebile lungo il bordo inferiore dell immagine
        per impedire clonazioni fraudolente da parte di truffatori online.
        """
        try:
            image = Image.open(BytesIO(image_bytes)).convert("RGBA")
            width, height = image.size

            # Crea layer trasparente
            overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(overlay)

            # Dimensione font proporzionale
            font_size = max(14, int(height * 0.035))
            try:
                # Prova font di sistema, altrimenti default
                font = ImageFont.load_default()
            except Exception:
                font = None

            # Disegna rettangolo scuro semitrasparente in basso
            banner_height = font_size + 16
            draw.rectangle(
                [(0, height - banner_height), (width, height)],
                fill=(2, 6, 23, 160)  # Slate-950 con 60% opacità
            )

            # Testo watermark arancione / bianco semitrasparente
            text_pos = (16, height - banner_height + 8)
            draw.text(text_pos, text, fill=(245, 158, 11, 230), font=font)  # Amber-500

            # Fonde le immagini
            watermarked = Image.alpha_composite(image, overlay)
            
            # Ritorna JPEG compresso di qualità elevata
            output = BytesIO()
            rgb_image = watermarked.convert("RGB")
            rgb_image.save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue()
        except Exception as e:
            logger.warning(f"Impossibile applicare filigrana all'immagine: {e}")
            return image_bytes

