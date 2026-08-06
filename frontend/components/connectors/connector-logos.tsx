interface LogoProps {
  className?: string;
}

const BASE = "h-4 w-4 shrink-0";

export function BigQueryLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <circle cx="10.6" cy="10.6" r="7.4" fill="none" stroke="#4285F4" strokeWidth="2.2" />
      <path
        d="m16.2 16.2 4.1 4.1"
        stroke="#4285F4"
        strokeWidth="2.6"
        strokeLinecap="round"
        fill="none"
      />
      <g fill="#4285F4">
        <rect x="7.4" y="10.6" width="1.9" height="4" rx=".5" />
        <rect x="10.4" y="7.6" width="1.9" height="7" rx=".5" />
        <rect x="13.4" y="11.8" width="1.9" height="2.8" rx=".5" />
      </g>
    </svg>
  );
}

export function SnowflakeLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <g stroke="#29B5E8" strokeWidth="1.7" strokeLinecap="round">
        <path d="M12 3v18M4.2 7.5l15.6 9M19.8 7.5l-15.6 9" />
      </g>
      <g fill="#29B5E8">
        <circle cx="12" cy="3.6" r="1.5" />
        <circle cx="12" cy="20.4" r="1.5" />
        <circle cx="4.6" cy="7.8" r="1.5" />
        <circle cx="19.4" cy="16.2" r="1.5" />
        <circle cx="19.4" cy="7.8" r="1.5" />
        <circle cx="4.6" cy="16.2" r="1.5" />
      </g>
    </svg>
  );
}

export function RedshiftLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <path d="M12 2 4 4.4v15.2L12 22V2Z" fill="#205B99" />
      <path d="M12 2l8 2.4v15.2L12 22V2Z" fill="#5193CE" />
      <path d="M9.6 8.4h1.6v7.2H9.6zM12.8 6.4h1.6v11.2h-1.6z" fill="#fff" opacity=".85" />
    </svg>
  );
}

export function SqlServerLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <path
        d="M5.6 5.6v12.8c0 1.4 2.86 2.5 6.4 2.5s6.4-1.1 6.4-2.5V5.6H5.6Z"
        fill="#A91D1B"
      />
      <ellipse cx="12" cy="5.6" rx="6.4" ry="2.5" fill="#CC2927" />
      <ellipse cx="12" cy="5.6" rx="3.9" ry="1.4" fill="#E8514F" />
      <g fill="#fff" opacity=".55">
        <ellipse cx="12" cy="11.6" rx="6.4" ry="2.1" fillOpacity=".18" />
        <ellipse cx="12" cy="15.6" rx="6.4" ry="2.1" fillOpacity=".12" />
      </g>
    </svg>
  );
}

export function MySqlLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <path
        d="M2.8 15.9c3-.5 5.4-1.9 7.2-4.2 1.9-2.4 4.3-3.8 7.2-4.1 1.6-.2 3 0 4 .5l-.9 2c-.8-.3-1.8-.4-2.9-.3-2.3.3-4.1 1.4-5.6 3.3-2.2 2.8-5.1 4.5-8.6 5.1l-.4-2.3Z"
        fill="#00758F"
      />
      <path
        d="M9.1 16.7c1.5.9 2.5 2.1 3 3.6l-2.2.6c-.3-1-.9-1.8-1.9-2.4l1.1-1.8Z"
        fill="#00758F"
      />
      <circle cx="17.8" cy="10.4" r="1.05" fill="#F29111" />
    </svg>
  );
}

export function PostgresLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <path
        d="M12 2.4c-3.9 0-7.4 1.6-7.4 5.2 0 2 .3 4.3 1 6.5.7 2.3 1.7 4.4 2.9 5.6.6.6 1.4.6 2-.1.4-.5.8-1.3 1-2.2.3.1.6.1.9.1s.6 0 .9-.1c.2.9.6 1.7 1 2.2.6.7 1.4.7 2 .1 1.2-1.2 2.2-3.3 2.9-5.6.7-2.2 1-4.5 1-6.5 0-3.6-3.5-5.2-7.4-5.2Z"
        fill="#336791"
      />
      <g fill="#fff">
        <ellipse cx="9.5" cy="8.6" rx="1.15" ry="1.35" />
        <ellipse cx="14.5" cy="8.6" rx="1.15" ry="1.35" />
      </g>
      <g fill="#336791">
        <circle cx="9.6" cy="8.8" r=".5" />
        <circle cx="14.4" cy="8.8" r=".5" />
      </g>
      <path d="M10.4 12.4h3.2c.3 0 .5.4.3.7l-1.6 2a.4.4 0 0 1-.6 0l-1.6-2c-.2-.3 0-.7.3-.7Z" fill="#fff" opacity=".55" />
    </svg>
  );
}

export function GoogleSheetsLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <path d="M14.4 2H6.6A1.6 1.6 0 0 0 5 3.6v16.8A1.6 1.6 0 0 0 6.6 22h10.8a1.6 1.6 0 0 0 1.6-1.6V6.6L14.4 2Z" fill="#0F9D58" />
      <path d="M14.4 2v3.1c0 .83.67 1.5 1.5 1.5H19L14.4 2Z" fill="#0B7C46" />
      <path
        d="M8.3 10.4h7.4v7.2H8.3v-7.2Zm1.3 1.3v1.3h2.1v-1.3H9.6Zm3.4 0v1.3h2.1v-1.3H13Zm-3.4 2.5v1.3h2.1v-1.3H9.6Zm3.4 0v1.3h2.1v-1.3H13Z"
        fill="#fff"
      />
    </svg>
  );
}

export function ExcelLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <path d="M14.4 2H6.6A1.6 1.6 0 0 0 5 3.6v16.8A1.6 1.6 0 0 0 6.6 22h10.8a1.6 1.6 0 0 0 1.6-1.6V6.6L14.4 2Z" fill="#217346" />
      <path d="M14.4 2v3.1c0 .83.67 1.5 1.5 1.5H19L14.4 2Z" fill="#17512F" />
      <path d="m9.1 10.6 1.7 2.7-1.8 2.9h1.6l1-1.8 1 1.8h1.7l-1.9-2.9 1.8-2.7h-1.6l-1 1.7-.9-1.7H9.1Z" fill="#fff" />
    </svg>
  );
}

export function RestApiLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <rect x="2.5" y="4.5" width="19" height="15" rx="2.5" fill="#527f79" />
      <path
        d="M8.6 9.4 6 12l2.6 2.6M15.4 9.4 18 12l-2.6 2.6M13.2 8.4l-2.4 7.2"
        stroke="#fff"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
    </svg>
  );
}

export function SalesforceLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <path
        d="M9.9 6.6a3.4 3.4 0 0 1 5.6-.9 4 4 0 0 1 5.6 3.7 3.9 3.9 0 0 1-3.9 3.9c-.3 0-.6 0-.9-.1a2.9 2.9 0 0 1-3.8 1.2 3.2 3.2 0 0 1-5.9-.4 3.6 3.6 0 0 1-.7.1A3.4 3.4 0 0 1 2.5 11a3.4 3.4 0 0 1 2.6-3.3 3.9 3.9 0 0 1 4.8-1.1Z"
        fill="#00A1E0"
      />
    </svg>
  );
}

export function CsvLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <path d="M14.4 2H6.6A1.6 1.6 0 0 0 5 3.6v16.8A1.6 1.6 0 0 0 6.6 22h10.8a1.6 1.6 0 0 0 1.6-1.6V6.6L14.4 2Z" fill="#687080" />
      <path d="M14.4 2v3.1c0 .83.67 1.5 1.5 1.5H19L14.4 2Z" fill="#4A505C" />
      <path d="M8 11h8v1.3H8zM8 13.7h8V15H8zM8 16.4h5.2v1.3H8z" fill="#fff" />
    </svg>
  );
}

export function SupabaseLogo({ className = BASE }: LogoProps) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden focusable="false">
      <defs>
        <linearGradient id="supabase-bolt" x1="4" y1="21" x2="17" y2="10" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#249361" />
          <stop offset="100%" stopColor="#3ECF8E" />
        </linearGradient>
      </defs>
      <path
        d="M13.2 22.4c-.6.75-1.8.34-1.8-.62V13.9H4.75c-1.09 0-1.69-1.25-1.02-2.1L10.8 1.6c.6-.75 1.8-.34 1.8.62v7.88h6.65c1.09 0 1.7 1.25 1.02 2.1l-7.07 10.2Z"
        fill="url(#supabase-bolt)"
      />
      <path
        d="M12.6 10.1V2.22c0-.96-1.2-1.37-1.8-.62L3.73 11.8c-.67.85-.07 2.1 1.02 2.1H12.6v-3.8Z"
        fill="#3ECF8E"
        opacity=".45"
      />
    </svg>
  );
}

export const CONNECTOR_LOGOS = {
  bigquery: BigQueryLogo,
  snowflake: SnowflakeLogo,
  redshift: RedshiftLogo,
  sqlserver: SqlServerLogo,
  mysql: MySqlLogo,
  postgresql: PostgresLogo,
  supabase: SupabaseLogo,
  google_sheets: GoogleSheetsLogo,
  excel: ExcelLogo,
  rest_api: RestApiLogo,
  salesforce: SalesforceLogo,
  csv: CsvLogo,
} as const;

export type ConnectorLogoKey = keyof typeof CONNECTOR_LOGOS;
