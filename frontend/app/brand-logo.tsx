type BrandLogoProps = {
  tone?: 'light' | 'dark';
  width?: number | string;
  className?: string;
};

/** The supplied animated wordmark, cropped in CSS without altering its source frames. */
export function BrandLogo({tone = 'light', width = 145, className = ''}: BrandLogoProps) {
  return <span className={`mimas-wordmark mimas-wordmark--${tone} ${className}`.trim()} style={{width}} aria-hidden="true">
    <img src={tone === 'light' ? '/brand/mimas-white.gif' : '/brand/mimas-black.gif'}
      width={852} height={480} alt="" draggable={false} />
    <span className="mimas-wordmark-static"><b>mimas</b></span>
  </span>;
}
