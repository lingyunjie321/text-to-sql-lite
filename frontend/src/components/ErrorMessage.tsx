interface ErrorMessageProps {
  message: string;
}

export function ErrorMessage({ message }: ErrorMessageProps): JSX.Element {
  return (
    <div className="errorMessage" role="alert">
      {message}
    </div>
  );
}
